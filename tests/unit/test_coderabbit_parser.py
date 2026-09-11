"""Tests for the CodeRabbit parser, driven by real captured CR comments/reviews.

Fixtures were pulled live from haexmas/holzi PR #26/#27 (2026-09-11) — CR's
actual current markup, not a guessed/historical format (see research.md R3).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.coderabbit.parser import parse_cr

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _line_comment(body: str, path: str = "src-tauri/src/chat/commands.rs", line: int = 211) -> dict:
    return {"id": 1, "path": path, "line": None, "original_line": line, "body": body}


def test_parse_line_comment_with_static_analysis_details() -> None:
    body = (FIXTURES / "cr_line_comment_potential_issue.md").read_text()
    findings = parse_cr([_line_comment(body, line=211)])
    assert len(findings) == 1
    f = findings[0]
    assert f.tool == "coderabbit"
    assert f.file == "src-tauri/src/chat/commands.rs"
    assert f.line_start == 211
    assert f.line_end == 211
    assert f.severity == "major"  # from "_🟠 Major_"
    assert f.category == "bug"  # infer_category picks up "session"/"emitting" -> falls to default bug-ish? see below
    assert "chat.session" in f.title
    assert "load_model" in f.body
    # The <details> blocks (static analysis scripts, AI-agent prompt) must not leak into title/body
    assert "Script executed" not in f.body
    assert "Prompt for AI Agents" not in f.body
    assert "cr-indicator-types" not in f.body


def test_parse_simple_line_comment_single_details_block() -> None:
    body = (FIXTURES / "cr_line_comment_simple.md").read_text()
    findings = parse_cr([_line_comment(body, line=514)])
    assert len(findings) == 1
    f = findings[0]
    assert f.line_start == 514
    assert f.severity == "major"
    assert "chat.last_active_model_id" in f.title


def test_line_comment_without_indicator_marker_is_skipped() -> None:
    """A reply like '✅ Addressed in commit ...' with no path is a meta comment; with
    a path but no cr-indicator-types marker it's a human reply, not a finding."""
    findings = parse_cr([_line_comment("Thanks, fixed in the next commit!", line=10)])
    assert findings == []


def test_comment_without_path_and_no_outside_diff_section_yields_nothing() -> None:
    """Issue-level comments (walkthrough, 'review finished') carry no path and no
    Outside-diff-range section — must not raise, must yield zero findings."""
    findings = parse_cr([{"id": 2, "body": "## Walkthrough\n\nThis PR adds..."}])
    assert findings == []


def test_empty_body_skipped() -> None:
    assert parse_cr([{"id": 3, "path": "a.py", "body": ""}]) == []
    assert parse_cr([{"id": 4, "body": "   "}]) == []


def test_multiple_line_comments_all_parsed() -> None:
    body1 = (FIXTURES / "cr_line_comment_potential_issue.md").read_text()
    body2 = (FIXTURES / "cr_line_comment_simple.md").read_text()
    findings = parse_cr([
        _line_comment(body1, line=211),
        _line_comment(body2, path="src-tauri/src/chat/commands.rs", line=514),
    ])
    assert len(findings) == 2
    lines = {f.line_start for f in findings}
    assert lines == {211, 514}


def test_outside_diff_range_extracted_from_review_body() -> None:
    body = (FIXTURES / "cr_review_with_outside_diff_range.md").read_text()
    # Review-level bodies have no `path` key (unlike line comments).
    findings = parse_cr([{"id": 5, "body": body}])
    assert len(findings) == 1
    f = findings[0]
    assert f.file == "specs/002-onboarding-model-prefs/contracts/tauri-commands.md"
    assert f.line_start == 152
    assert f.line_end == 165
    assert f.severity == "major"  # "_🟠 Major_"
    assert "idempotent" in f.title.lower()
    # The duplicate "Actionable comments posted" / "Prompt for all review comments"
    # digest must not produce a second, duplicate finding.
    assert "Prompt for AI Agents" not in f.body


def test_review_body_without_outside_diff_range_yields_nothing() -> None:
    """A plain 'Actionable comments posted: N' summary with no outside-diff-range
    section is a pure duplicate of the line comments — must yield zero findings
    (not double-count)."""
    body = "**Actionable comments posted: 3**\n\nSome digest text, no outside-diff section here."
    assert parse_cr([{"id": 6, "body": body}]) == []


@pytest.mark.parametrize(
    "severity_word,expected",
    [
        ("🔴 Critical", "critical"),
        ("🟠 Major", "major"),
        ("🟡 Minor", "minor"),
        ("⚪ Trivial", "nit"),
    ],
)
def test_severity_word_mapping(severity_word: str, expected: str) -> None:
    body = (
        f"_🎯 Functional Correctness_ | _{severity_word}_ | _⚡ Quick win_\n\n"
        "**Some title.** Some body text.\n\n"
        "<!-- cr-indicator-types:potential_issue -->\n"
    )
    findings = parse_cr([_line_comment(body)])
    assert len(findings) == 1
    assert findings[0].severity == expected


def test_unrecognized_severity_word_falls_back_to_indicator_default() -> None:
    """A severity word CR doesn't use any known keyword for falls back to the
    indicator-type default rather than an arbitrary guess."""
    body = (
        "_🎯 Functional Correctness_ | _🔵 Enhancement_ | _⚡ Quick win_\n\n"
        "**Some title.** Some body text.\n\n"
        "<!-- cr-indicator-types:verification -->\n"
    )
    findings = parse_cr([_line_comment(body)])
    assert len(findings) == 1
    assert findings[0].severity == "info"  # _INDICATOR_SEVERITY["verification"]


def test_missing_severity_line_falls_back_to_indicator_type() -> None:
    """No _cat_|_sev_|_effort_ line at all -> fall back to indicator-type defaults."""
    body = "**A nitpick title.** Body text.\n\n<!-- cr-indicator-types:nitpick -->\n"
    findings = parse_cr([_line_comment(body)])
    assert len(findings) == 1
    assert findings[0].severity == "nit"
    assert findings[0].category == "style"
