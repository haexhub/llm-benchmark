"""Wrapper for the gito.bot CLI + parser for its code-review-report.json format.

gito JSON layout (from gito.report_struct.Report):
    {"summary": str,
     "issues": {
        "path/to/file.py": [
            {"id": int|str, "title": str, "details": str,
             "severity": int|None, "confidence": int|None,
             "tags": [str], "file": str,
             "affected_lines": [{"start_line": int, "end_line": int, "proposal": str|None}]},
            …
        ]
     }}

Written by `gito review` to `<out_dir>/code-review-report.json`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from benchmark.models import Category, Finding, Severity
from benchmark.tools.base import RunResult, run_cli

GITO_REPORT_FILENAME = "code-review-report.json"


def build_gito_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """gito uses microcore under the hood — NOT litellm-style names/prefixes.

    Verified live: microcore reads `LLM_API_TYPE`/`LLM_API_BASE`/`LLM_API_KEY`/`MODEL`
    and expects a bare model id. A litellm-style `openai/<model>` prefix (correct
    for pr-agent) breaks microcore's model-name handling here.
    """
    from benchmark.config import env

    e = dict(base_env or os.environ)
    e["LLM_API_TYPE"] = "openai"
    tool_base = env("TOOL_LLM_BASE_URL")
    tool_key = env("TOOL_LLM_API_KEY")
    tool_model = env("TOOL_LLM_MODEL")
    if tool_base:
        e["LLM_API_BASE"] = tool_base
    if tool_key:
        e["LLM_API_KEY"] = tool_key
    if tool_model:
        e["MODEL"] = tool_model
    return e


def run_gito_on_pr(
    owner: str,
    repo: str,
    pr: int,
    base_sha: str,
    head_sha: str,
    clone_dir: Path,
    out_dir: Path,
    timeout: int = 600,
) -> RunResult:
    """Clone the repo, fetch the pinned Head SHA, and run gito against that diff.

    gito's own `--url` clones exactly that URL — passing a PR URL there fails
    (`git clone <pr-url>` isn't a valid clone target; verified live). Its `--path`
    option is unimplemented upstream (`# @todo: implement` in gito's own
    cli.py). The only working mode for a specific PR is running gito with no
    `--url` (its "use local repo at cwd" branch) inside an already-checked-out
    clone, with `--what`/`--against` as explicit refs.
    """
    clone_dir.mkdir(parents=True, exist_ok=True)
    repo_url = f"https://github.com/{owner}/{repo}.git"
    local_head_ref = f"pr-{pr}-head"

    clone_result = run_cli(["git", "clone", "--quiet", repo_url, str(clone_dir)], timeout=timeout)
    if not clone_result.ok:
        return clone_result
    fetch_result = run_cli(
        ["git", "fetch", "--quiet", "origin", f"{head_sha}:{local_head_ref}"],
        timeout=timeout,
        cwd=clone_dir,
    )
    if not fetch_result.ok:
        return fetch_result

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "uv", "tool", "run", "--from", "gito.bot", "gito",
        "review",
        "--what", local_head_ref,
        "--against", base_sha,
        "--no-merge-base",
        # Must be absolute: gito runs with cwd=clone_dir (below), so a relative
        # --out would resolve against the clone dir instead of the caller's cwd.
        # Verified live: a relative out_dir produced
        # "<clone_dir>/<out_dir>/code-review-report.json" instead of "<out_dir>/...".
        "--out", str(out_dir.resolve()),
        "--no-post-comment",
    ]
    return run_cli(cmd, timeout=timeout, env=build_gito_env(), cwd=clone_dir)


def parse_gito_json(payload: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    issues_by_file = payload.get("issues") or {}
    for file_path, issue_list in issues_by_file.items():
        if not isinstance(issue_list, list):
            continue
        for issue in issue_list:
            for affected in _iter_affected_lines(issue):
                start, end, proposal = affected
                title = (issue.get("title") or "issue").strip()
                details = (issue.get("details") or title).strip()
                findings.append(
                    Finding(
                        id=uuid4(),
                        tool="gito",
                        file=file_path,
                        line_start=start,
                        line_end=end,
                        severity=_map_severity(issue.get("severity")),
                        category=_map_category(issue.get("tags") or []),
                        title=title[:200],
                        body=details,
                        suggestion=proposal,
                        raw=dict(issue),
                    )
                )
    return findings


def load_gito_findings(path: Path) -> list[Finding]:
    with path.open() as fh:
        payload = json.load(fh)
    return parse_gito_json(payload)


def _iter_affected_lines(issue: dict[str, Any]):
    affected = issue.get("affected_lines") or []
    if not affected:
        yield (0, 0, None)
        return
    for a in affected:
        try:
            start = int(a.get("start_line") or 0)
            end_raw = a.get("end_line")
            end = int(end_raw) if end_raw is not None else start
        except (TypeError, ValueError):
            start = end = 0
        if end < start:
            end = start
        proposal = a.get("proposal")
        yield (start, end, proposal)


def _map_severity(raw: Any) -> Severity:
    """gito uses integer 1..5 (higher = more severe)."""
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return "minor"
    if v >= 5:
        return "critical"
    if v == 4:
        return "major"
    if v == 3:
        return "minor"
    if v == 2:
        return "nit"
    return "info"


def _map_category(tags: list[str]) -> Category:
    tags_lc = {t.lower() for t in tags if isinstance(t, str)}
    if tags_lc & {"bug", "correctness", "error-handling"}:
        return "bug"
    if tags_lc & {"security", "vulnerability", "auth"}:
        return "security"
    if tags_lc & {"performance", "perf"}:
        return "perf"
    if tags_lc & {"test", "testing"}:
        return "test"
    if tags_lc & {"docs", "doc", "docstring"}:
        return "doc"
    if tags_lc & {"style", "naming", "formatting"}:
        return "style"
    return "other"
