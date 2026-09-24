from __future__ import annotations

import logging
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

import httpx
import typer
import yaml
from rich.console import Console

from benchmark.config import env, load_env, load_live_repositories, load_repos
from benchmark.corpus import (
    CorpusValidationError,
    build_coverage_matrix,
    materialize_review_input,
    record_curator_approval,
    validate_defect_label_scope,
    validate_protected_defect_label,
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
runengine_app = typer.Typer(no_args_is_help=True, help="Corpus-Runs gegen gito/pr-agent planen und auswerten.")
app.add_typer(corpus_app, name="corpus")
app.add_typer(live_app, name="live")
app.add_typer(runengine_app, name="runengine")
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
    corpus_dir: Annotated[
        Path, typer.Option("--corpus-dir", help="Pfad zum öffentlichen Corpus-Suite-Verzeichnis.")
    ],
    curator_id: Annotated[str, typer.Option(help="ID des Kurators, der diese Freigabe verantwortet.")],
    runs: Annotated[int, typer.Option(help="Anzahl deterministischer Reproducer-Läufe.")] = 3,
) -> None:
    """Läuft den Reproducer mehrfach und trägt bei Erfolg die Curator-Freigabe ein.

    Nur ausführen, nachdem ein Mensch Label, Scope und Reproducer inhaltlich geprüft hat.
    """
    label_file = label_file.resolve()
    try:
        label = validate_protected_defect_label(label_file)
    except CorpusValidationError as error:
        console.print(f"[red]Approval failed: {error}[/red]")
        raise typer.Exit(1) from error
    if label.approval.state != "pending":
        console.print(f"[red]Approval failed: label is already {label.approval.state}[/red]")
        raise typer.Exit(1)
    oracle_item_dir = label_file.parent
    item_id = oracle_item_dir.name
    reproducer_root = (oracle_item_dir / "reproducers").resolve()
    reproducer_entry = (reproducer_root / label.reproducer_id).resolve()
    if reproducer_entry.parent != reproducer_root or reproducer_entry == reproducer_root:
        console.print("[red]Approval failed: reproducer_id escapes the canonical directory[/red]")
        raise typer.Exit(1)
    if reproducer_entry.is_dir():
        reproducer = reproducer_entry / "reproducer.sh"
    else:
        reproducer = reproducer_entry
    if not reproducer.is_file():
        console.print(f"[red]Approval failed: missing canonical reproducer: {reproducer}[/red]")
        raise typer.Exit(1)

    public_item_dir = corpus_dir.resolve() / "items" / item_id
    with TemporaryDirectory(prefix="benchmark-approval-") as work_directory:
        try:
            runner_input = materialize_review_input(
                corpus_dir, item_id, Path(work_directory) / "runner-input"
            )
            manifest = yaml.safe_load(runner_input.manifest_file.read_text())
            validate_defect_label_scope(
                public_item_dir / "repo.bundle", manifest["head_sha"], label, item_id
            )
            determinism = verify_reproducer_determinism(
                reproducer, runner_input.head_directory, runs=runs
            )
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
            label_file,
            curator_id=curator_id,
            evidence_digest=sha256(
                f"{item_id}:{manifest['head_sha']}:{label.reproducer_id}:"
                f"{determinism.evidence_digest}".encode()
            ).hexdigest(),
        )
    except CorpusValidationError as error:
        console.print(f"[red]Approval failed:[/red] {error}")
        raise typer.Exit(1) from error
    console.print(
        f"[green]{label.id} approved by {curator_id} ({label.approval.state}, "
        f"{determinism.run_count}/{determinism.run_count} deterministic runs).[/green]"
    )


@corpus_app.command("coverage")
def corpus_coverage(
    corpus_dir: Annotated[Path, typer.Argument(help="Pfad zu einem öffentlichen Corpus-Suite-Verzeichnis.")],
    oracle_dir: Annotated[Path, typer.Argument(help="Pfad zum protected Oracle-Verzeichnis der Suite.")],
) -> None:
    """Zeigt Item-/Label-Verteilung und fehlende Strata für eine Corpus-Suite."""
    try:
        matrix = build_coverage_matrix(corpus_dir, oracle_dir)
    except CorpusValidationError as error:
        console.print(f"[red]Coverage report failed:[/red] {error}")
        raise typer.Exit(1) from error
    console.print(
        f"Items: {matrix.item_count} (clean: {matrix.clean_count}, "
        f"seeded: {matrix.seeded_count}, clean ratio: {matrix.clean_ratio:.0%})"
    )
    console.print(
        f"Labels: {matrix.decision_ready_label_count} decision-ready, "
        f"{matrix.pending_label_count} pending"
    )
    for dimension, counts in (
        ("language", matrix.by_language),
        ("partition", matrix.by_partition),
        ("source", matrix.by_source),
        ("diff_size_bucket", matrix.by_diff_size),
        ("difficulty", matrix.by_difficulty),
        ("category", matrix.by_category),
        ("severity", matrix.by_severity),
    ):
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        console.print(f"  {dimension}: {rendered or '(none)'}")
    if matrix.missing_strata:
        console.print(f"[yellow]Missing strata: {', '.join(matrix.missing_strata)}[/yellow]")
    else:
        console.print("[green]No zero-count strata.[/green]")


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


@runengine_app.command("candidate-register")
def runengine_candidate_register(
    slug: Annotated[str, typer.Option(help="gito|pr-agent")],
    tool_version: Annotated[str, typer.Option(help="Exakte Tool-Version.")],
    package_digest: Annotated[str, typer.Option(help="Package/Image-Digest der Tool-Installation.")],
) -> None:
    """Registriert eine Kandidaten-Version (FR-012 Vorstufe; Capability-Probe folgt in US4)."""
    from benchmark.runengine.candidate import register_candidate
    from benchmark.runengine.db import connect

    model_config_hash = sha256(
        f"{env('TOOL_LLM_BASE_URL', '')}:{env('TOOL_LLM_MODEL', '')}".encode()
    ).hexdigest()
    conn = connect()
    try:
        candidate = register_candidate(
            conn, slug=slug, tool_version=tool_version, package_digest=package_digest,
            model_endpoint_config_hash=model_config_hash,
        )
    finally:
        conn.close()
    console.print(f"[green]Registered[/green] {candidate.slug} {candidate.id}")


@runengine_app.command("plan-create")
def runengine_plan_create(
    suite_dir: Annotated[Path, typer.Option(help="z.B. review-corpus/review-v1")],
    candidate: Annotated[list[str], typer.Option(help="Kandidaten-Slug, mehrfach angebbar.")],
    repetitions: Annotated[int, typer.Option(help="Repetitionen pro Item/Kandidat.")] = 3,
    retry_cap: Annotated[int, typer.Option(help="Max. automatische Retries pro Zelle.")] = 3,
    score_policy_version: Annotated[str, typer.Option()] = "review-v1-policy-1",
) -> None:
    """Erstellt einen ExecutionPlan (idempotent pro Actor) und legt seine Attempts an."""
    from benchmark.runengine.artifacts import ArtifactStore
    from benchmark.runengine.attempts import create_attempts
    from benchmark.runengine.candidate import get_candidate
    from benchmark.runengine.db import connect
    from benchmark.runengine.plan import PlanRequest, create_plan

    suite_manifest = yaml.safe_load((suite_dir / "suite.yaml").read_text())
    item_ids = sorted(p.name for p in (suite_dir / "items").iterdir() if p.is_dir())
    model = env("TOOL_LLM_MODEL", "unknown")

    conn = connect()
    try:
        candidate_versions = []
        for slug in candidate:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM candidate_version WHERE slug = %s ORDER BY registered_at DESC LIMIT 1",
                    (slug,),
                )
                row = cur.fetchone()
            if row is None:
                console.print(f"[red]No registered candidate_version for slug {slug!r}.[/red]")
                raise typer.Exit(1)
            candidate_versions.append(get_candidate(conn, row[0]))

        request = PlanRequest(
            suite_version_digest=suite_manifest["content_digest"],
            candidate_version_ids=tuple(c.id for c in candidate_versions),
            repetitions=repetitions,
            retry_cap=retry_cap,
            score_policy_version=score_policy_version,
            created_by=env("USER", "unknown"),
        )
        plan = create_plan(conn, request)
        store = ArtifactStore()
        store.ensure_bucket()
        attempts = create_attempts(
            conn, store, plan, item_ids, model=model,
            config_hash_by_candidate={c.id: c.model_endpoint_config_hash for c in candidate_versions},
        )
    finally:
        conn.close()
    console.print(f"[green]Plan {plan.id}[/green] — {len(attempts)} attempts queued")


@runengine_app.command("plan-run")
def runengine_plan_run(
    plan_id: Annotated[str, typer.Argument()],
    suite_dir: Annotated[Path, typer.Option(help="z.B. review-corpus/review-v1")],
    oracle_dir: Annotated[
        Path | None,
        typer.Option(help="Protected Oracle-Verzeichnis (z.B. corpus-oracle/review-v1); ohne wird nicht evaluiert."),
    ] = None,
) -> None:
    """Führt alle `queued` Attempts eines Plans aus (US1/US2)."""
    from uuid import UUID

    from benchmark.runengine.artifacts import ArtifactStore
    from benchmark.runengine.attempts import run_attempt
    from benchmark.runengine.candidate import get_candidate
    from benchmark.runengine.db import connect

    conn = connect()
    store = ArtifactStore()
    store.ensure_bucket()
    workspace_root = _ctx["runs_dir"] / "runengine" / "workspaces"
    try:
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, item_id, candidate_version_id FROM attempt "
                    "WHERE plan_id = %s AND status = 'queued' LIMIT 1",
                    (UUID(plan_id),),
                )
                row = cur.fetchone()
            if row is None:
                break
            attempt_id, item_id, candidate_version_id = row
            candidate_version = get_candidate(conn, candidate_version_id)
            outcome = run_attempt(
                conn, store, attempt_id=attempt_id, corpus_root=suite_dir, item_id=item_id,
                candidate_slug=candidate_version.slug, model=env("TOOL_LLM_MODEL", "unknown"),
                config_hash=candidate_version.model_endpoint_config_hash,
                workspace_root=workspace_root, runs_dir=_ctx["runs_dir"],
                oracle_root=oracle_dir,
            )
            if outcome is None:
                console.print("[yellow]Resource lease busy — stopping this run.[/yellow]")
                break
    finally:
        conn.close()
    console.print(f"[green]Plan {plan_id} run pass complete.[/green]")


@runengine_app.command("attempt-list")
def runengine_attempt_list(plan_id: Annotated[str, typer.Option()]) -> None:
    """Listet alle Attempts eines Plans mit Status/Terminal-Reason."""
    from uuid import UUID

    from benchmark.runengine.db import connect

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, item_id, candidate_version_id, sample_index, status, terminal_reason "
                "FROM attempt WHERE plan_id = %s ORDER BY item_id, candidate_version_id, sample_index",
                (UUID(plan_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    for attempt_id, item_id, candidate_version_id, sample_index, status, terminal_reason in rows:
        suffix = f" — {terminal_reason}" if terminal_reason else ""
        console.print(f"{attempt_id} {item_id} {candidate_version_id} #{sample_index} [bold]{status}[/bold]{suffix}")


@runengine_app.command("attempt-show")
def runengine_attempt_show(attempt_id: Annotated[str, typer.Argument()]) -> None:
    """Zeigt Details eines einzelnen Attempts."""
    from uuid import UUID

    from benchmark.runengine.db import connect

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM attempt WHERE id = %s", (UUID(attempt_id),))
            columns = [d.name for d in cur.description]
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        console.print(f"[red]No such attempt: {attempt_id}[/red]")
        raise typer.Exit(1)
    for name, value in zip(columns, row, strict=True):
        console.print(f"{name}: {value}")


@runengine_app.command("score-show")
def runengine_score_show(
    plan_id: Annotated[str, typer.Option(help="Plan-ID.")],
) -> None:
    """Zeigt pro Kandidat Quality-/Operational-Metriken plus das Novel-Findings-Panel (US3)."""
    from uuid import UUID

    from benchmark.runengine.db import connect
    from benchmark.runengine.scoring import compute_operational_metrics, compute_scores

    conn = connect()
    try:
        plan_uuid = UUID(plan_id)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT candidate_version_id, suite_version_digest, score_policy_version "
                "FROM execution_plan WHERE id = %s",
                (plan_uuid,),
            )
            plan_row = cur.fetchone()
            if plan_row is None:
                console.print(f"[red]No such plan: {plan_id}[/red]")
                raise typer.Exit(1)
            _, suite_version_digest, score_policy_version = plan_row
            cur.execute(
                "SELECT DISTINCT candidate_version_id, slug FROM attempt "
                "JOIN candidate_version ON candidate_version.id = attempt.candidate_version_id "
                "WHERE plan_id = %s",
                (plan_uuid,),
            )
            candidates = cur.fetchall()

        for candidate_version_id, slug in candidates:
            metrics = compute_scores(conn, plan_id=plan_uuid, candidate_version_id=candidate_version_id)
            operational = compute_operational_metrics(
                conn, plan_id=plan_uuid, candidate_version_id=candidate_version_id
            )
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT nfr.verdict, count(*) FROM novel_finding_review nfr
                    JOIN evaluation e ON e.id = nfr.evaluation_id
                    JOIN attempt a ON a.id = e.attempt_id
                    WHERE a.plan_id = %s AND a.candidate_version_id = %s
                    GROUP BY nfr.verdict
                    """,
                    (plan_uuid, candidate_version_id),
                )
                novel_counts = dict(cur.fetchall())

            console.print(f"\n[bold]{slug}[/bold] ({candidate_version_id})")
            console.print(f"  suite_version_digest: sha256:{suite_version_digest}")
            console.print(f"  score_policy_version: {score_policy_version}")
            for name, metric in metrics.items():
                spread = (
                    f" [range {metric.range_min:.3f}-{metric.range_max:.3f}]"
                    if metric.range_min is not None
                    else ""
                )
                console.print(f"  {name}: {metric.value} (n={metric.sample_count}){spread}")
            console.print("  operational:")
            for name, metric in operational.items():
                console.print(f"    {name}: {metric.value} (n={metric.sample_count})")
            console.print(
                "  novel_findings (never affects the score above): "
                f"plausible={novel_counts.get('plausible_novel_defect', 0)} "
                f"not_defect={novel_counts.get('not_defect', 0)} "
                f"inconclusive={novel_counts.get('inconclusive', 0)}"
            )
    finally:
        conn.close()


@runengine_app.command("gold-candidates-export")
def runengine_gold_candidates_export(
    plan_id: Annotated[str, typer.Option(help="Plan-ID.")],
) -> None:
    """Gibt alle `proposed` Gold-Label-Kandidaten eines Plans aus (FR-009b)."""
    from uuid import UUID

    from benchmark.runengine.db import connect

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT gc.id, gc.item_id, gc.location_file, gc.location_line_start,
                       gc.location_line_end, gc.finding_summary, gc.judge_reasoning, gc.created_at
                FROM gold_label_candidate gc
                JOIN novel_finding_review nfr ON nfr.id = gc.novel_finding_review_id
                JOIN evaluation e ON e.id = nfr.evaluation_id
                JOIN attempt a ON a.id = e.attempt_id
                WHERE a.plan_id = %s AND gc.status = 'proposed'
                """,
                (UUID(plan_id),),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        console.print("[yellow]No proposed Gold-label candidates for this plan.[/yellow]")
        return
    for candidate_id, item_id, file, line_start, line_end, summary, reasoning, created_at in rows:
        console.print(f"[bold]{candidate_id}[/bold] {item_id}:{file}:{line_start}-{line_end}")
        console.print(f"  summary: {summary}")
        console.print(f"  judge reasoning: {reasoning}")
        console.print(f"  proposed_at: {created_at}")


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
