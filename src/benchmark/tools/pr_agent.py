"""Wrapper for the pr-agent CLI + parser for its --json-output structure.

pr-agent JSON layout (from pr_agent/settings/pr_reviewer_prompts.toml):
    {"review": {
        "key_issues_to_review": [
            {"relevant_file": str, "issue_header": str, "issue_content": str,
             "start_line": int, "end_line": int},
             …
        ],
        "security_concerns": str,
        …
    }}
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from benchmark.models import Finding
from benchmark.tools.base import RunResult, run_cli


def build_pragent_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Compose the environment pr-agent needs, mapping our TOOL_LLM_* vars to its expected names."""
    from benchmark.config import env

    e = dict(base_env or os.environ)
    tool_base = env("TOOL_LLM_BASE_URL")
    tool_key = env("TOOL_LLM_API_KEY")
    tool_model = env("TOOL_LLM_MODEL")
    if tool_base:
        e["OPENAI__API_BASE"] = tool_base
        e["OPENAI_API_BASE"] = tool_base
    if tool_key:
        e["OPENAI__KEY"] = tool_key
        e["OPENAI_API_KEY"] = tool_key
    if tool_model:
        # pr-agent uses litellm-style model identifiers; the caller usually passes them as-is.
        # Prefix with openai/ if not already prefixed and looks like a bare model name.
        model = tool_model if "/" in tool_model else f"openai/{tool_model}"
        e["CONFIG__MODEL"] = model
    gh_token = env("GH_TOKEN")
    if gh_token:
        e["GITHUB__USER_TOKEN"] = gh_token
    e["CONFIG__PUBLISH_OUTPUT"] = "false"
    return e


def run_pragent_on_diff(diff_file: Path, json_output: Path, timeout: int = 600) -> RunResult:
    """Run pr-agent in plain-diff local mode: no GitHub round-trip, just a local diff file."""
    cmd = [
        "uv", "tool", "run", "--from", "pr-agent", "pr-agent",
        "--diff-file", str(diff_file),
        "--json-output", str(json_output),
        "review",
    ]
    return run_cli(cmd, timeout=timeout, env=build_pragent_env())


def run_pragent_on_pr(pr_url: str, json_output: Path, timeout: int = 600) -> RunResult:
    """Run pr-agent against a GitHub PR URL. Requires GH_TOKEN in the env."""
    cmd = [
        "uv", "tool", "run", "--from", "pr-agent", "pr-agent",
        "--pr_url", pr_url,
        "--json-output", str(json_output),
        "review",
    ]
    return run_cli(cmd, timeout=timeout, env=build_pragent_env())


def parse_pragent_json(payload: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    review = payload.get("review") or {}
    issues = review.get("key_issues_to_review") or []
    for issue in issues:
        file_path = (issue.get("relevant_file") or "").strip()
        if not file_path:
            continue
        try:
            start = int(issue.get("start_line") or 0)
            end = int(issue.get("end_line") or start)
        except (TypeError, ValueError):
            start = end = 0
        if end < start:
            end = start
        header = (issue.get("issue_header") or "").strip() or "issue"
        content = (issue.get("issue_content") or "").strip() or header
        findings.append(
            Finding(
                id=uuid4(),
                tool="pr-agent",
                file=file_path,
                line_start=start,
                line_end=end,
                severity="major",  # pr-agent's key_issues sind alle "notable"; keine explicit severity
                category=_infer_category(header, content),
                title=header[:200],
                body=content,
                suggestion=None,
                raw=dict(issue),
            )
        )
    return findings


def load_pragent_findings(path: Path) -> list[Finding]:
    with path.open() as fh:
        payload = json.load(fh)
    return parse_pragent_json(payload)


def _infer_category(header: str, content: str) -> str:
    text = f"{header} {content}".lower()
    if any(k in text for k in ("security", "injection", "xss", "csrf", "auth", "secret")):
        return "security"
    if any(k in text for k in ("perf", "latency", "n+1", "memory")):
        return "perf"
    if any(k in text for k in ("test", "coverage", "assert")):
        return "test"
    if any(k in text for k in ("doc", "docstring", "readme")):
        return "doc"
    if any(k in text for k in ("bug", "issue", "exception", "error", "crash", "leak", "race", "undefined")):
        return "bug"
    if any(k in text for k in ("style", "naming", "format", "refactor", "cleanup")):
        return "style"
    return "other"
