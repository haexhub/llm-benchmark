"""Parse CodeRabbit review bodies into normalized Findings.

CR posts three kinds of GitHub content on a PR:
- Line-level review comments (each has `path`, `line`, `body`)
- Review-level summaries (only `body`, no line anchor)
- Issue-level comments (general comments on the PR)

Their `body` markdown contains prefix-tagged blocks like `⚠️ Potential issue`,
`🛠️ Refactor suggestion`, `🧹 Nitpick`, `✅ Verification`. This parser splits the
body at those prefixes and produces one Finding per block.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from benchmark.models import Category, Finding, Severity

_PREFIX_SEVERITY: dict[str, Severity] = {
    "potential issue": "major",
    "refactor suggestion": "minor",
    "nitpick": "nit",
    "verification": "info",
    "suggestion": "minor",
}

_PREFIX_CATEGORY: dict[str, Category] = {
    "potential issue": "bug",
    "refactor suggestion": "style",
    "nitpick": "style",
    "verification": "test",
    "suggestion": "style",
}

# Matches a header line like: **⚠️ Potential issue**  or  **🧹 Nitpick (assertive)**
_HEADER_RE = re.compile(
    r"\*\*(?:[^\w\s]+\s*)?"
    r"(Potential issue|Refactor suggestion|Nitpick(?:\s*\([^)]*\))?|Verification(?:\s+agent)?|Suggestion)"
    r"\*\*",
    re.IGNORECASE,
)

# Matches a file+line anchor like: `path/to/file.py` \n\n `142-158`:
_ANCHOR_RE = re.compile(
    r"`([^`\n]+\.[a-zA-Z0-9]+)`\s*\n\s*`(\d+)(?:-(\d+))?`\s*:",
)


def parse_cr(raw_comments: list[dict[str, Any]]) -> list[Finding]:
    """Parse the full list of coderabbitai[bot] comments (from all three GH endpoints).

    Each dict must contain at least a `body` string; optionally `path`, `line`,
    `original_line` for line-level comments.
    """
    findings: list[Finding] = []
    for comment in raw_comments:
        body = comment.get("body") or ""
        if not body.strip():
            continue

        line_hint_path = comment.get("path")
        line_hint_line = comment.get("line") or comment.get("original_line")

        blocks = _extract_blocks(body)
        for prefix_label, block_body, anchor in blocks:
            file_path, start, end = anchor
            if file_path is None and line_hint_path:
                file_path = line_hint_path
                start = start or (int(line_hint_line) if line_hint_line else 0)
                end = end or start
            if file_path is None:
                # Summary-only block without any file anchor — skip; it's meta chatter.
                continue

            severity = _PREFIX_SEVERITY.get(prefix_label.lower(), "info")
            category = _PREFIX_CATEGORY.get(prefix_label.lower(), "other")
            title = _title_from(prefix_label, block_body)
            findings.append(
                Finding(
                    id=uuid4(),
                    tool="coderabbit",
                    file=file_path,
                    line_start=start or 0,
                    line_end=end or start or 0,
                    severity=severity,
                    category=category,
                    title=title,
                    body=block_body.strip(),
                    suggestion=_suggestion_from(block_body),
                    raw={"comment_id": comment.get("id"), "prefix": prefix_label},
                )
            )
    return findings


def _extract_blocks(body: str) -> list[tuple[str, str, tuple[str | None, int | None, int | None]]]:
    """Return list of (prefix_label, block_body, (file, line_start, line_end))."""
    headers = list(_HEADER_RE.finditer(body))
    if not headers:
        return []

    results: list[tuple[str, str, tuple[str | None, int | None, int | None]]] = []
    for i, m in enumerate(headers):
        prefix_label = m.group(1)
        # Body is text from this header up to next header (or end)
        block_start = m.end()
        block_end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        block_body = body[block_start:block_end].strip()

        # Find the *nearest preceding* file anchor (within reasonable distance)
        pre_body = body[: m.start()]
        anchor_match = None
        for am in _ANCHOR_RE.finditer(pre_body):
            anchor_match = am  # last one wins
        file_path: str | None = None
        line_start: int | None = None
        line_end: int | None = None
        if anchor_match:
            file_path = anchor_match.group(1)
            line_start = int(anchor_match.group(2))
            line_end = int(anchor_match.group(3)) if anchor_match.group(3) else line_start

        results.append((prefix_label, block_body, (file_path, line_start, line_end)))
    return results


def _title_from(prefix_label: str, block_body: str) -> str:
    first_line = next((ln.strip() for ln in block_body.splitlines() if ln.strip()), "")
    if not first_line:
        return prefix_label
    return first_line[:200]


def _suggestion_from(block_body: str) -> str | None:
    """If a fenced code block appears, treat it as the suggestion."""
    m = re.search(r"```(?:\w+)?\n(.*?)```", block_body, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None
