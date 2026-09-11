"""Parse CodeRabbit output into normalized Findings.

CR posts three kinds of GitHub content on a PR:
- Line-level review comments (`pulls/{n}/comments`): each has `path` + `line`
  (or `original_line`) and is the primary, reliable source of findings. Every
  genuine finding carries a machine-readable `<!-- cr-indicator-types:X -->`
  HTML comment (X in {potential_issue, refactor_suggestion, nitpick,
  verification, suggestion}); comments without it are replies/meta chatter
  and are skipped.
- Review-level summaries (`pulls/{n}/reviews`): mostly a duplicate digest of
  the line comments plus an "Outside diff range comments" section — findings
  CodeRabbit could not anchor to a line comment because they fall outside the
  diff. That section is the only unique information in a review body; the
  rest is skipped.
- Issue-level comments (`issues/{n}/comments`): PR-level meta only (walkthrough
  summary, "review finished" replies) — never contain findings.

The category/severity/effort line (`_<category>_ | _<severity>_ | _<effort>_`)
and the `**bold title**` line are the two structural anchors used to extract a
title, severity and category from the free-text body.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from benchmark.categorize import infer_category
from benchmark.models import Category, Finding, Severity

_INDICATOR_SEVERITY: dict[str, Severity] = {
    "potential_issue": "major",
    "refactor_suggestion": "minor",
    "nitpick": "nit",
    "verification": "info",
    "suggestion": "minor",
}
_INDICATOR_CATEGORY: dict[str, Category] = {
    "potential_issue": "bug",
    "refactor_suggestion": "style",
    "nitpick": "style",
    "verification": "test",
    "suggestion": "style",
}

_INDICATOR_RE = re.compile(r"<!--\s*cr-indicator-types:([a-z_]+)\s*-->")
# No line-start anchor: in a plain line comment this stands alone on its own
# line, but in an "Outside diff range" block it's prefixed by `` `152-165`: ``.
_SEV_LINE_RE = re.compile(r"_(.+?)_\s*\|\s*_(.+?)_\s*\|\s*_(.+?)_")
_TITLE_RE = re.compile(r"\*\*(.+?)\*\*")
_DETAILS_RE = re.compile(r"<details>.*?</details>", re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def parse_cr(raw_comments: list[dict[str, Any]]) -> list[Finding]:
    """Parse the combined list of coderabbitai[bot] items from all three GH endpoints."""
    findings: list[Finding] = []
    for comment in raw_comments:
        body = comment.get("body") or ""
        if not body.strip():
            continue

        path = comment.get("path")
        if path:
            finding = _parse_line_comment(comment, path, body)
            if finding:
                findings.append(finding)
        else:
            findings.extend(_parse_outside_diff_range(body))
    return findings


def _parse_line_comment(comment: dict[str, Any], path: str, body: str) -> Finding | None:
    if not _INDICATOR_RE.search(body):
        return None  # reply/meta comment, not a structured finding
    line = comment.get("line") or comment.get("original_line") or 0
    return _finding_from_block(path, int(line), int(line), body, raw_extra={"comment_id": comment.get("id")})


# "Outside diff range comments (N)" is the only unique-information section in a
# review body; everything else duplicates the line comments already parsed.
# Consuming through the wrapper's own "</summary><blockquote>" (not just the
# header text) keeps it from being re-matched as a fake per-file section below.
_OUTSIDE_HEADER_RE = re.compile(r"Outside diff range comments[^<]*</summary><blockquote>")
_OUTSIDE_END_RE = re.compile(r"<details>\s*<summary>[^<]*Prompt for all review comments")
_FILE_SECTION_RE = re.compile(r"<summary>([^<(]+?)\s*\(\d+\)</summary><blockquote>(.*?)</blockquote>", re.DOTALL)
_LINE_RANGE_RE = re.compile(r"`(\d+)(?:-(\d+))?`:\s*_.+?_\s*\|\s*_.+?_\s*\|\s*_.+?_")


def _parse_outside_diff_range(body: str) -> list[Finding]:
    start_match = _OUTSIDE_HEADER_RE.search(body)
    if not start_match:
        return []
    end_match = _OUTSIDE_END_RE.search(body, start_match.end())
    section = body[start_match.end() : end_match.start() if end_match else len(body)]
    # Nested content is blockquoted ("> " per line); strip that for easier parsing.
    section = re.sub(r"^>\s?", "", section, flags=re.MULTILINE)

    results: list[Finding] = []
    for file_match in _FILE_SECTION_RE.finditer(section):
        file_path = file_match.group(1).strip()
        file_body = file_match.group(2)
        line_matches = list(_LINE_RANGE_RE.finditer(file_body))
        for i, lm in enumerate(line_matches):
            block_end = line_matches[i + 1].start() if i + 1 < len(line_matches) else len(file_body)
            block = file_body[lm.start() : block_end]
            start = int(lm.group(1))
            end = int(lm.group(2)) if lm.group(2) else start
            finding = _finding_from_block(file_path, start, end, block, raw_extra={"source": "outside_diff_range"})
            if finding:
                results.append(finding)
    return results


def _finding_from_block(
    file_path: str, line_start: int, line_end: int, raw_block: str, raw_extra: dict[str, Any]
) -> Finding | None:
    indicator_match = _INDICATOR_RE.search(raw_block)
    indicator = indicator_match.group(1) if indicator_match else None

    clean = _DETAILS_RE.sub("", raw_block)

    severity: Severity | None = None
    category: Category | None = None
    sev_match = _SEV_LINE_RE.search(clean)
    if sev_match:
        category_word, severity_word, _effort_word = sev_match.groups()
        severity = _severity_from_word(severity_word)
        category = infer_category(f"{category_word} {clean}")

    if severity is None:
        severity = _INDICATOR_SEVERITY.get(indicator, "info") if indicator else "info"
    if category is None:
        category = _INDICATOR_CATEGORY.get(indicator, "other") if indicator else "unknown"

    title_match = _TITLE_RE.search(clean)
    if title_match:
        title = title_match.group(1).strip()
        body_text = _HTML_COMMENT_RE.sub("", clean[title_match.end() :]).strip()
    else:
        title = (indicator or "finding").replace("_", " ")
        body_text = _HTML_COMMENT_RE.sub("", clean).strip()

    if not body_text:
        body_text = title
    if not title:
        return None

    return Finding(
        id=uuid4(),
        tool="coderabbit",
        file=file_path,
        line_start=line_start,
        line_end=line_end,
        severity=severity,
        category=category,
        title=title[:200],
        body=body_text,
        suggestion=None,
        raw={"indicator": indicator, **raw_extra},
    )


def _severity_from_word(word: str) -> Severity | None:
    w = word.lower()
    if "critical" in w or "blocker" in w:
        return "critical"
    if "major" in w:
        return "major"
    if "minor" in w:
        return "minor"
    if "trivial" in w or "nit" in w:
        return "nit"
    return None
