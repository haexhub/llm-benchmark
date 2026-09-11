"""Tests for the per-PR report renderer, incl. regression for double-counted
agreed_with_cr in the classification summary (classify_findings labels both
the CR-side and the tool-side of a match "agreed_with_cr" — the per-PR
summary must count that as one agreement per tool, not two)."""
from __future__ import annotations

from uuid import uuid4

from benchmark.models import Finding, JudgeVerdict, Match
from benchmark.reports.per_pr import render_per_pr


def _f(tool, file="a.py", start=10, end=None, title="t", body="b"):
    return Finding(
        id=uuid4(),
        tool=tool,
        file=file,
        line_start=start,
        line_end=end if end is not None else start,
        severity="major",
        category="bug",
        title=title,
        body=body,
    )


def _verdict(confidence=0.9):
    return JudgeVerdict(same=True, confidence=confidence, reason="x", judge_model="m", prompt_hash="0" * 64)


def test_agreed_with_cr_counted_once_per_tool_not_twice() -> None:
    cr = _f("coderabbit", title="CR title")
    gito = _f("gito", title="gito title")
    pragent = _f("pr-agent", title="pragent title")
    matches = [
        Match(a_id=cr.id, b_id=gito.id, structural_overlap_lines=1, verdict=_verdict(), classification="same"),
        Match(a_id=cr.id, b_id=pragent.id, structural_overlap_lines=1, verdict=_verdict(), classification="same"),
    ]
    md = render_per_pr(
        "owner", "repo", 1,
        {"coderabbit": [cr], "gito": [gito], "pr-agent": [pragent]},
        matches,
    )
    assert "gito**: agreed_with_cr=1, unique_to_tool=0, missed_from_cr=0" in md
    assert "pr-agent**: agreed_with_cr=1, unique_to_tool=0, missed_from_cr=0" in md


def test_unique_and_missed_findings_rendered() -> None:
    cr = _f("coderabbit", title="only CR sees this")
    gito_unique = _f("gito", start=50, title="only gito sees this")
    md = render_per_pr(
        "owner", "repo", 1,
        {"coderabbit": [cr], "gito": [gito_unique], "pr-agent": []},
        matches=[],
    )
    assert "only CR sees this" in md
    assert "only gito sees this" in md
    # The CR finding isn't matched by either tool, so it's "missed" from both
    # tools' perspective — that's independent of gito's own unique finding.
    assert "gito**: agreed_with_cr=0, unique_to_tool=1, missed_from_cr=1" in md
    assert "pr-agent**: agreed_with_cr=0, unique_to_tool=0, missed_from_cr=1" in md


def test_empty_pr_run_renders_without_crashing() -> None:
    md = render_per_pr("owner", "repo", 1, {"coderabbit": [], "gito": [], "pr-agent": []}, matches=[])
    assert "PR-Review Benchmark" in md
    assert "agreed_with_cr=0" in md
