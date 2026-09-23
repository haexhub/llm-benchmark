from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console

from benchmark.config import env, load_env, load_live_repositories, load_repos
from benchmark.corpus import (
    CorpusValidationError,
    record_curator_approval,
    validate_public_corpus,
    verify_reproducer_determinism,
)
from benchmark.github.fetch import fetch_diff_for_refs, fetch_pr_refs
from benchmark.live import LiveObservationStore, LivePRIngestor, LivePRSnapshot
from benchmark.logging_setup import setup_logging
from benchmark.models import Finding

app = typer.Typer(no_args_is_help=True, help="PR-Review Benchmark CLI.")
corpus_app = typer.Typer(no_args_is_help=True, help="Benchmark-Corpus verwalten und prüfen.")
live_app = typer.Typer(no_args_is_help=True, help="Private Live-PR-Shadow-Reviews verwalten.")
app.add_typer(corpus_app, name="corpus")
app.add_typer(live_app, name="live")
console = Console()
log = logging.getLogger("benchmark")


@app.callback()
def main(
    config: Annotated[Path, typer.Option(help="Pfad zu repos.yaml.")] = Path("config/repos.yaml"),
    runs_dir: Annotated[Path, typer.Option(help="Pfad zum runs/-Verzeichnis.")] = Path("runs"),
    reports_dir: Annotated[Path, typer.Option(help="Pfad zum reports/-Verzeichnis.")] = Path("reports"),
    log_level: Annotated[str | None, typer.Option(help="DEBUG|INFO|WARNING|ERROR")] = None,
) -> None:
    load_env()
    setup_logging(log_level)
    _ctx.update(config=config, runs_dir=runs_dir, reports_dir=reports_dir)


_ctx: dict = {}


@corpus_app.command("validate")
def validate_corpus(
    corpus_dir: Annotated[Path, typer.Argument(help="Pfad zu einem öffentlichen Corpus-Suite-Verzeichnis.")],
) -> None:
    """Prüft, ob ein öffentlicher Review-Corpus vollständig und reproduzierbar ist."""
    try:
        report = validate_public_corpus(corpus_dir)
    except CorpusValidationError as error:
        console.print(f"[red]Corpus validation failed:[/red] {error}")
        raise typer.Exit(1) from error
    console.print(f"[green]Validated {report.item_count} public corpus item(s).[/green]")


@corpus_app.command("approve-label")
def approve_label(
    label_file: Annotated[Path, typer.Argument(help="Pfad zur protected ground-truth.yaml.")],
    reproducer: Annotated[Path, typer.Option(help="Pfad zum Reproducer-Skript.")],
    fixture: Annotated[Path, typer.Option(help="Pfad zur materialisierten, oracle-freien Head-Fixture.")],
    curator_id: Annotated[str, typer.Option(help="ID des Kurators, der diese Freigabe verantwortet.")],
    runs: Annotated[int, typer.Option(help="Anzahl deterministischer Reproducer-Läufe.")] = 3,
) -> None:
    """Läuft den Reproducer mehrfach und trägt bei Erfolg die Curator-Freigabe ein.

    Nur ausführen, nachdem ein Mensch Label, Scope und Reproducer inhaltlich geprüft hat.
    """
    try:
        determinism = verify_reproducer_determinism(reproducer, fixture, runs=runs)
    except CorpusValidationError as error:
        console.print(f"[red]Reproducer verification failed:[/red] {error}")
        raise typer.Exit(1) from error
    if not determinism.deterministic:
        console.print(
            f"[red]Reproducer did not pass all {determinism.run_count} isolated runs.[/red]"
        )
        raise typer.Exit(1)
    try:
        label = record_curator_approval(
            label_file, curator_id=curator_id, evidence_digest=determinism.evidence_digest
        )
    except CorpusValidationError as error:
        console.print(f"[red]Approval failed:[/red] {error}")
        raise typer.Exit(1) from error
    console.print(
        f"[green]{label.id} approved by {curator_id} ({label.approval.state}, "
        f"{determinism.run_count}/{determinism.run_count} deterministic runs).[/green]"
    )


@live_app.command("ingest")
def ingest_live_pr(
    repo: Annotated[str, typer.Option(help="Opt-in-Repository als owner/name.")],
    pr: Annotated[int, typer.Option(help="PR-Nummer.")],
) -> None:
    """Erfasst einen PR als unveränderlichen, privaten Live-Shadow-Snapshot."""
    config_path = _ctx.get("config") or Path("config/repos.yaml")
    integration = next(
        (item for item in load_live_repositories(config_path) if item.slug == repo), None
    )
    if integration is None:
        console.print(f"[red]No enabled live integration for {repo}.[/red]")
        raise typer.Exit(1)
    ingestor = LivePRIngestor(
        LiveObservationStore(_ctx["runs_dir"] / "live"),
        fetch_refs=fetch_pr_refs,
        fetch_diff=fetch_diff_for_refs,
    )
    recorded = ingestor.ingest(integration, pr)
    action = "Created" if recorded.created else "Reused"
    snapshot = recorded.observation.snapshot
    console.print(
        f"[green]{action} live observation[/green] {repo}#{pr} "
        f"{snapshot.base_sha[:12]}...{snapshot.head_sha[:12]}"
    )


def _run_live_gito(snapshot: LivePRSnapshot, work_dir: Path, timeout: int) -> list[Finding]:
    from benchmark.tools.gito import GITO_REPORT_FILENAME, load_gito_findings, run_gito_on_pr

    owner, name = snapshot.repository.split("/", 1)
    clone_dir = work_dir / "gito-clone"
    out_dir = work_dir / "gito-workdir"
    result = run_gito_on_pr(
        owner, name, snapshot.pr_number, snapshot.base_sha, snapshot.head_sha, clone_dir, out_dir,
        timeout=timeout,
    )
    if not result.ok:
        raise RuntimeError(f"gito CLI failed rc={result.returncode}: {result.stderr[:400]}")
    report_path = out_dir / GITO_REPORT_FILENAME
    if not report_path.exists():
        raise RuntimeError(
            f"gito produced no report at {report_path} (rc={result.returncode}); "
            f"stdout tail: {result.stdout[-400:]!r}; stderr tail: {result.stderr[-400:]!r}"
        )
    return load_gito_findings(report_path)


def _run_live_pragent(diff_file: Path, work_dir: Path, timeout: int) -> list[Finding]:
    import json

    from benchmark.tools.pr_agent import parse_pragent_json, run_pragent_on_diff

    raw_out = work_dir / "pr-agent-raw.json"
    result = run_pragent_on_diff(diff_file, raw_out, timeout=timeout)
    if not result.ok:
        raise RuntimeError(f"pr-agent CLI failed rc={result.returncode}: {result.stderr[:400]}")
    if not raw_out.exists():
        raise RuntimeError(
            f"pr-agent produced no JSON output at {raw_out} (rc={result.returncode}); "
            f"stdout tail: {result.stdout[-400:]!r}; stderr tail: {result.stderr[-400:]!r}"
        )
    with raw_out.open() as fh:
        payload = json.load(fh)
    return parse_pragent_json(payload)


@live_app.command("run")
def run_live_pr(
    repo: Annotated[str, typer.Option(help="Opt-in-Repository als owner/name.")],
    pr: Annotated[int, typer.Option(help="PR-Nummer.")],
) -> None:
    """Treibt Ingest, CodeRabbit-Baseline und Challenger-Runs für einen Live-PR voran.

    Idempotent und beliebig oft erneut aufrufbar (z. B. per Cron) — jeder Aufruf
    erledigt nur noch offene Arbeit und leitet den Lifecycle-State neu her.
    """
    import os
    import tempfile
    from datetime import UTC, datetime

    from benchmark.github.fetch import fetch_cr_comments
    from benchmark.live import (
        CodeRabbitBaselineCapture,
        LiveChallengerScheduler,
        LiveShadowRunner,
        ResourceUnavailable,
        SqliteResourceLeaseStore,
        run_live_shadow_review,
    )
    from benchmark.pipeline import TOOL_TIMEOUT_SECONDS

    config_path = _ctx.get("config") or Path("config/repos.yaml")
    integration = next(
        (item for item in load_live_repositories(config_path) if item.slug == repo), None
    )
    if integration is None:
        console.print(f"[red]No enabled live integration for {repo}.[/red]")
        raise typer.Exit(1)

    live_dir = _ctx["runs_dir"] / "live"
    store = LiveObservationStore(live_dir)
    ingestor = LivePRIngestor(store, fetch_refs=fetch_pr_refs, fetch_diff=fetch_diff_for_refs)

    def _fetch_cr_comments_for_slug(repository: str, pr_number: int):
        owner, name = repository.split("/", 1)
        return fetch_cr_comments(owner, name, pr_number)

    baseline_capture = CodeRabbitBaselineCapture(store, fetch_comments=_fetch_cr_comments_for_slug)
    lease_store = SqliteResourceLeaseStore(_ctx["runs_dir"] / "run-engine.sqlite3")
    runner = LiveShadowRunner(
        store, LiveChallengerScheduler(), lease_store, worker_id=f"live-cli-{os.getpid()}"
    )

    work_dir = live_dir / "work" / repo.replace("/", "__") / str(pr)
    work_dir.mkdir(parents=True, exist_ok=True)

    def _gito(snapshot: LivePRSnapshot) -> list[Finding]:
        with tempfile.TemporaryDirectory(dir=work_dir, prefix="gito-") as attempt_dir:
            return _run_live_gito(snapshot, Path(attempt_dir), TOOL_TIMEOUT_SECONDS)

    def _pragent(snapshot: LivePRSnapshot) -> list[Finding]:
        with tempfile.TemporaryDirectory(dir=work_dir, prefix="pr-agent-") as attempt_dir:
            return _run_live_pragent(
                store.diff_path(snapshot), Path(attempt_dir), TOOL_TIMEOUT_SECONDS
            )

    try:
        observation = run_live_shadow_review(
            ingestor,
            baseline_capture,
            runner,
            store,
            integration,
            pr,
            {"gito": _gito, "pr-agent": _pragent},
            now=datetime.now(UTC),
        )
    except ResourceUnavailable as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error

    console.print(
        f"[green]{observation.state}[/green] {repo}#{pr} {observation.snapshot.head_sha[:12]}"
    )


def _print_check(label: str, ok: bool, detail: str = "") -> None:
    icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
    line = f"{icon} {label}"
    if detail:
        line += f" — {detail}"
    console.print(line)


@app.command()
def check() -> int:
    """Prüft Env, gh-Auth, LLM-Endpoints und CLI-Tools. Exit 0 wenn alles OK, sonst 1."""
    all_ok = True

    # 1. .env-Vollständigkeit
    required = ["TOOL_LLM_BASE_URL", "TOOL_LLM_API_KEY", "TOOL_LLM_MODEL"]
    missing = [k for k in required if not env(k)]
    if missing:
        all_ok = False
        _print_check(".env vollständig (TOOL_LLM_*)", False, f"fehlt: {', '.join(missing)}")
    else:
        _print_check(".env vollständig (TOOL_LLM_*)", True)

    provider = env("JUDGE_LLM_PROVIDER", "anthropic")
    judge_required = ["JUDGE_LLM_API_KEY", "JUDGE_LLM_MODEL"]
    if provider == "openai":
        judge_required.append("JUDGE_LLM_BASE_URL")
    judge_missing = [k for k in judge_required if not env(k)]
    if judge_missing:
        all_ok = False
        _print_check(f"Judge ({provider}) vollständig", False, f"fehlt: {', '.join(judge_missing)}")
    else:
        _print_check(f"Judge ({provider}) vollständig", True)

    # 2. gh
    if shutil.which("gh") is None:
        all_ok = False
        _print_check("gh (GitHub CLI) verfügbar", False, "nicht im PATH")
    else:
        proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        ok = proc.returncode == 0
        all_ok = all_ok and ok
        _print_check("gh auth status", ok, "" if ok else proc.stderr.strip().splitlines()[0] if proc.stderr else "auth failed")

    # 3. TOOL_LLM /models
    base = env("TOOL_LLM_BASE_URL")
    key = env("TOOL_LLM_API_KEY")
    model = env("TOOL_LLM_MODEL")
    if base and key:
        try:
            resp = httpx.get(
                f"{base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            models = {m.get("id") for m in data.get("data", []) if isinstance(m, dict)}
            if model in models:
                _print_check(f"TOOL_LLM_MODEL '{model}' verfügbar", True)
            else:
                all_ok = False
                sample = ", ".join(sorted(models)[:5])
                _print_check(
                    f"TOOL_LLM_MODEL '{model}' verfügbar",
                    False,
                    f"nicht in /models — verfügbar u.a.: {sample}",
                )
        except httpx.HTTPError as exc:
            all_ok = False
            _print_check("TOOL_LLM /models erreichbar", False, str(exc))
    else:
        _print_check("TOOL_LLM /models erreichbar", False, "skipped: fehlende TOOL_LLM_*")

    # 4. pr-agent / gito
    for tool_name, package in [("pr-agent", "pr-agent"), ("gito", "gito.bot")]:
        proc = subprocess.run(
            ["uv", "tool", "run", "--from", package, tool_name, "--help"],
            capture_output=True,
            text=True,
        )
        ok = proc.returncode == 0
        all_ok = all_ok and ok
        _print_check(f"{tool_name} --help", ok)

    # 5. Judge-Dummy
    if provider == "anthropic":
        judge_key = env("JUDGE_LLM_API_KEY")
        judge_model = env("JUDGE_LLM_MODEL")
        if judge_key and judge_model:
            try:
                from anthropic import Anthropic

                judge_base = env("JUDGE_LLM_BASE_URL")
                client_kwargs = {"api_key": judge_key}
                if judge_base:
                    client_kwargs["base_url"] = judge_base
                client = Anthropic(**client_kwargs)
                _ = client.messages.create(
                    model=judge_model,
                    max_tokens=8,
                    messages=[{"role": "user", "content": "ping"}],
                )
                where = f" via {judge_base}" if judge_base else ""
                _print_check(f"Judge (Anthropic, {judge_model}){where} antwortet", True)
            except Exception as exc:  # noqa: BLE001
                all_ok = False
                _print_check(f"Judge (Anthropic, {judge_model}) antwortet", False, str(exc)[:200])
    elif provider == "openai":
        judge_key = env("JUDGE_LLM_API_KEY")
        judge_model = env("JUDGE_LLM_MODEL")
        judge_base = env("JUDGE_LLM_BASE_URL")
        if judge_key and judge_model and judge_base:
            try:
                from openai import OpenAI

                client = OpenAI(api_key=judge_key, base_url=judge_base)
                _ = client.chat.completions.create(
                    model=judge_model,
                    max_tokens=8,
                    messages=[{"role": "user", "content": "ping"}],
                )
                _print_check(f"Judge (OpenAI, {judge_model}) antwortet", True)
            except Exception as exc:  # noqa: BLE001
                all_ok = False
                _print_check(f"Judge (OpenAI, {judge_model}) antwortet", False, str(exc)[:200])
    else:
        all_ok = False
        _print_check("JUDGE_LLM_PROVIDER valid", False, f"unbekannt: {provider!r}")

    # 6. repos.yaml
    try:
        repos = load_repos(_ctx.get("config") or Path("config/repos.yaml"))
        _print_check(f"repos.yaml lädt ({len(repos)} Repo(s))", True)
    except FileNotFoundError as exc:
        all_ok = False
        _print_check("repos.yaml lädt", False, str(exc))
    except Exception as exc:  # noqa: BLE001
        all_ok = False
        _print_check("repos.yaml lädt", False, str(exc)[:200])

    exit_code = 0 if all_ok else 1
    console.print()
    if all_ok:
        console.print("[bold green]Alle Checks OK.[/bold green]")
    else:
        console.print("[bold red]Mindestens ein Check fehlgeschlagen.[/bold red]")
    raise typer.Exit(exit_code)


def _resolve_repos():
    from benchmark import pipeline  # noqa: F401

    return load_repos(_ctx.get("config") or Path("config/repos.yaml"))


@app.command()
def fetch(
    repo: Annotated[str | None, typer.Option(help="Nur dieses Repo (owner/name).")] = None,
    pr: Annotated[int | None, typer.Option(help="Nur diese PR-Nummer.")] = None,
    force: Annotated[bool, typer.Option(help="Existierende Outputs überschreiben.")] = False,
) -> None:
    """PR-Diff + CodeRabbit-Baseline holen."""
    from benchmark import pipeline

    repos = _resolve_repos()
    pipeline.do_fetch(repos, _ctx["runs_dir"], force=force, active_repo=repo, active_pr=pr)


@app.command()
def run(
    repo: Annotated[str | None, typer.Option()] = None,
    pr: Annotated[int | None, typer.Option()] = None,
    force: Annotated[bool, typer.Option()] = False,
) -> None:
    """gito und pr-agent auf die PRs loslassen."""
    from benchmark import pipeline

    repos = _resolve_repos()
    pipeline.do_run(repos, _ctx["runs_dir"], force=force, active_repo=repo, active_pr=pr)


@app.command()
def match(
    repo: Annotated[str | None, typer.Option()] = None,
    pr: Annotated[int | None, typer.Option()] = None,
    force: Annotated[bool, typer.Option()] = False,
) -> None:
    """Findings-Paare matchen + Judge."""
    from benchmark import pipeline

    repos = _resolve_repos()
    pipeline.do_match(repos, _ctx["runs_dir"], force=force, active_repo=repo, active_pr=pr)


@app.command()
def report(
    repo: Annotated[str | None, typer.Option()] = None,
    pr: Annotated[int | None, typer.Option()] = None,
    force: Annotated[bool, typer.Option()] = False,
) -> None:
    """Reports rendern."""
    from benchmark import pipeline

    repos = _resolve_repos()
    pipeline.do_report(
        repos, _ctx["runs_dir"], _ctx["reports_dir"], force=force, active_repo=repo, active_pr=pr
    )


@app.command()
def all(
    repo: Annotated[str | None, typer.Option()] = None,
    pr: Annotated[int | None, typer.Option()] = None,
    force: Annotated[bool, typer.Option()] = False,
) -> None:
    """fetch → run → match → report in Sequenz."""
    from rich.progress import Progress, SpinnerColumn, TextColumn

    from benchmark import pipeline

    repos = _resolve_repos()
    phases = [
        ("fetch", lambda: pipeline.do_fetch(repos, _ctx["runs_dir"], force=force, active_repo=repo, active_pr=pr)),
        ("run", lambda: pipeline.do_run(repos, _ctx["runs_dir"], force=force, active_repo=repo, active_pr=pr)),
        ("match", lambda: pipeline.do_match(repos, _ctx["runs_dir"], force=force, active_repo=repo, active_pr=pr)),
        ("report", lambda: pipeline.do_report(repos, _ctx["runs_dir"], _ctx["reports_dir"], force=force, active_repo=repo, active_pr=pr)),
    ]
    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        transient=False,
        console=console,
    ) as progress:
        for name, fn in phases:
            task = progress.add_task(f"Phase {name}", total=None)
            fn()
            progress.update(task, description=f"Phase {name} — done", completed=1, total=1)
    console.print("[bold green]Alle Phasen abgeschlossen.[/bold green]")


@app.command()
def review(
    repo: Annotated[str | None, typer.Option()] = None,
    pr: Annotated[int | None, typer.Option()] = None,
    include_confident: Annotated[bool, typer.Option(help="Auch confident Matches sichten.")] = False,
    reviewer: Annotated[str | None, typer.Option(help="Name/Email für manual_review.json.")] = None,
) -> None:
    """Interaktive Sichtung unsicherer Matches."""
    from benchmark.review.interactive import run_review

    repos = _resolve_repos()
    run_review(
        repos,
        _ctx["runs_dir"],
        console=console,
        active_repo=repo,
        active_pr=pr,
        include_confident=include_confident,
        reviewer=reviewer,
    )


if __name__ == "__main__":
    app()
