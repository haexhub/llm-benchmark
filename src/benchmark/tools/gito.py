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
    """gito uses microcore/LiteLLM under the hood; the env var names are LLM_*"""
    from benchmark.config import env

    e = dict(base_env or os.environ)
    tool_base = env("TOOL_LLM_BASE_URL")
    tool_key = env("TOOL_LLM_API_KEY")
    tool_model = env("TOOL_LLM_MODEL")
    if tool_base:
        e["LLM_API_BASE"] = tool_base
        e["LLM_BASE_URL"] = tool_base
        e["OPENAI_API_BASE"] = tool_base
    if tool_key:
        e["LLM_API_KEY"] = tool_key
        e["OPENAI_API_KEY"] = tool_key
    if tool_model:
        e["LLM_MODEL"] = tool_model if tool_model.startswith("openai/") else f"openai/{tool_model}"
        e["MODEL"] = e["LLM_MODEL"]
    return e


def run_gito_on_pr(pr_url: str, out_dir: Path, pr_number: int, timeout: int = 600) -> RunResult:
    """Run gito against a GitHub PR URL. gito clones the repo internally."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "uv", "tool", "run", "--from", "gito.bot", "gito",
        "review",
        "--url", pr_url,
        "--pr", str(pr_number),
        "--out", str(out_dir),
        "--no-post-comment",
    ]
    return run_cli(cmd, timeout=timeout, env=build_gito_env())


def run_gito_on_local(repo_path: Path, out_dir: Path, what: str, against: str, timeout: int = 600) -> RunResult:
    """Run gito against a local clone (faster, no network round-trip)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "uv", "tool", "run", "--from", "gito.bot", "gito",
        "review",
        "--path", str(repo_path),
        "--what", what,
        "--against", against,
        "--out", str(out_dir),
        "--no-post-comment",
    ]
    return run_cli(cmd, timeout=timeout, env=build_gito_env())


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
