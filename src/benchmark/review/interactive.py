"""Interactive review of uncertain (or all) matches — writes/updates manual_review.json."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from benchmark.matching.aggregator import load_manual_reviews
from benchmark.models import Finding, ManualDecision, ManualReview, Match, RepoConfig

log = logging.getLogger("benchmark.review")

_DECISION_MAP: dict[str, ManualDecision] = {
    "s": "same",
    "d": "different",
    "u": "unclear",
}


def run_review(
    repos: list[RepoConfig],
    runs_dir: Path,
    *,
    console: Console,
    active_repo: str | None,
    active_pr: int | None,
    include_confident: bool,
    reviewer: str | None,
    prompt_fn: Callable[[str, list[str]], str] | None = None,
) -> None:
    """Iterate PR-Runs and prompt for each undecided match.

    `prompt_fn` is injected for tests; defaults to a Rich-based prompt.
    """
    reviewer = reviewer or _default_reviewer()
    prompt_fn = prompt_fn or _rich_prompt(console)

    for repo in repos:
        if active_repo and f"{repo.owner}/{repo.name}" != active_repo:
            continue
        for pr in repo.pr_numbers:
            if active_pr is not None and pr != active_pr:
                continue
            base = runs_dir / repo.slug / str(pr)
            matches_path = base / "matches.json"
            if not matches_path.exists():
                continue

            matches = _load_matches(matches_path)
            findings = _load_findings(base)
            manual_path = base / "manual_review.json"
            existing_reviews = {r.match_id for r in load_manual_reviews(manual_path)}

            to_review = [
                m for m in matches
                if m.id not in existing_reviews
                and (include_confident or m.classification == "uncertain")
            ]
            if not to_review:
                console.print(f"[green]✓[/green] {repo.slug}#{pr}: nichts offen.")
                continue

            console.print(f"[bold]{repo.slug}#{pr}: {len(to_review)} Match(es) zum Sichten[/bold]")
            for idx, match in enumerate(to_review, 1):
                a = _find(findings, match.a_id)
                b = _find(findings, match.b_id)
                if not a or not b:
                    log.warning("skip match %s: finding not found", match.id)
                    continue

                _render_pair(console, idx, len(to_review), match, a, b)
                answer = prompt_fn(
                    "[s]ame / [d]ifferent / [u]nclear / s[k]ip / [q]uit",
                    ["s", "d", "u", "k", "q"],
                )
                if answer == "q":
                    console.print("[yellow]quit[/yellow]")
                    return
                if answer == "k":
                    continue
                decision = _DECISION_MAP[answer]
                note = prompt_fn("Optional Note (leer = keine)", []) or None
                new_review = ManualReview(
                    match_id=match.id,
                    decision=decision,
                    note=note,
                    reviewer=reviewer,
                    ts=datetime.now(UTC),
                )
                _append_review(manual_path, new_review)


def _rich_prompt(console: Console) -> Callable[[str, list[str]], str]:
    def _prompt(msg: str, choices: list[str]) -> str:
        if choices:
            return Prompt.ask(msg, choices=choices, console=console)
        return Prompt.ask(msg, console=console, default="", show_default=False)
    return _prompt


def _render_pair(console: Console, idx: int, total: int, match: Match, a: Finding, b: Finding) -> None:
    from hashlib import sha256

    key = f"{match.id}"
    a_first = (sha256(key.encode()).digest()[0] & 1) == 0
    first, second = (a, b) if a_first else (b, a)

    def _fmt(f: Finding, label: str) -> str:
        return (
            f"[bold]{label}[/bold] — {f.file}:{f.line_start}-{f.line_end}\n"
            f"  severity: {f.severity} / {f.category}\n"
            f"  title:    {f.title}\n"
            f"  body:     {f.body}"
        )

    body = (
        f"{_fmt(first, 'A')}\n\n"
        f"{_fmt(second, 'B')}\n\n"
        f"Judge-Verdict: same={match.verdict.same}, confidence={match.verdict.confidence:.2f}\n"
        f"Judge-Reason:  {match.verdict.reason}"
    )
    console.print(Panel(body, title=f"Match {idx}/{total} — classification={match.classification}"))


def _find(findings: list[Finding], fid: UUID) -> Finding | None:
    return next((f for f in findings if f.id == fid), None)


def _load_findings(base: Path) -> list[Finding]:
    result: list[Finding] = []
    for filename in ("coderabbit.json", "gito.json", "pr-agent.json"):
        path = base / filename
        if not path.exists():
            continue
        with path.open() as fh:
            payload = json.load(fh)
        for item in payload.get("findings", []):
            result.append(Finding.model_validate(item))
    return result


def _load_matches(path: Path) -> list[Match]:
    with path.open() as fh:
        payload = json.load(fh)
    return [Match.model_validate(item) for item in payload.get("matches", [])]


def _append_review(path: Path, new: ManualReview) -> None:
    """Atomic append: read existing, append, write to .tmp, rename."""
    if path.exists():
        with path.open() as fh:
            payload = json.load(fh)
        reviews = payload.get("reviews", [])
    else:
        reviews = []
    reviews.append(json.loads(new.model_dump_json()))
    payload = {"schema_version": "1", "reviews": reviews}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    tmp.replace(path)


def _default_reviewer() -> str:
    for cmd in (["git", "config", "user.email"],):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:  # noqa: BLE001
            pass
    return os.environ.get("USER") or "unknown"
