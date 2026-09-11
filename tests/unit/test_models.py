from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from benchmark.models import (
    Finding,
    JudgeVerdict,
    ManualReview,
    Match,
    PerToolStats,
    RepoConfig,
)


def test_repo_config_slug() -> None:
    r = RepoConfig(owner="alice", name="proj", pr_numbers=[1])
    assert r.slug == "alice__proj"


def test_repo_config_rejects_empty_owner() -> None:
    with pytest.raises(ValidationError):
        RepoConfig(owner="", name="proj", pr_numbers=[1])


def test_finding_round_trip() -> None:
    original = Finding(
        tool="coderabbit",
        file="src/foo.py",
        line_start=10,
        line_end=12,
        severity="major",
        category="bug",
        title="Off-by-one",
        body="Loop bound is wrong",
        suggestion="range(n) → range(n+1)",
        raw={"source": "test"},
    )
    dumped = original.model_dump_json()
    restored = Finding.model_validate_json(dumped)
    assert restored == original


def test_finding_rejects_line_end_before_start() -> None:
    with pytest.raises(ValidationError):
        Finding(
            tool="gito",
            file="a.py",
            line_start=10,
            line_end=5,
            severity="minor",
            category="style",
            title="x",
            body="y",
        )


def test_finding_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        Finding(
            tool="gito",
            file="a.py",
            line_start=1,
            line_end=1,
            severity="oopsie",  # type: ignore[arg-type]
            category="style",
            title="x",
            body="y",
        )


def test_finding_rejects_title_too_long() -> None:
    with pytest.raises(ValidationError):
        Finding(
            tool="gito",
            file="a.py",
            line_start=1,
            line_end=1,
            severity="minor",
            category="style",
            title="x" * 201,
            body="y",
        )


def test_match_round_trip() -> None:
    v = JudgeVerdict(
        same=True,
        confidence=0.9,
        reason="Both mention off-by-one in same loop",
        judge_model="claude-sonnet-4-5",
        prompt_hash="a" * 64,
    )
    m = Match(a_id=uuid4(), b_id=uuid4(), structural_overlap_lines=3, verdict=v, classification="same")
    dumped = m.model_dump_json()
    restored = Match.model_validate_json(dumped)
    assert restored == m


def test_judge_verdict_rejects_bad_hash() -> None:
    with pytest.raises(ValidationError):
        JudgeVerdict(same=True, confidence=0.5, reason="x", judge_model="m", prompt_hash="abc")


def test_manual_review_round_trip() -> None:
    r = ManualReview(
        match_id=uuid4(),
        decision="same",
        note="both flag the same thing",
        reviewer="me@example.com",
        ts=datetime.now(UTC),
    )
    restored = ManualReview.model_validate_json(r.model_dump_json())
    assert restored == r


def test_per_tool_stats_minimum() -> None:
    s = PerToolStats(
        repo="alice/foo",
        tool="gito",
        findings_raw=10,
        findings_after_dedup=8,
        overlap_with_cr=3,
        unique_to_tool=5,
        missed_from_cr=2,
        avg_severity_score=2.5,
        category_breakdown={"bug": 3, "style": 5},
        failed_pr_count=0,
        total_pr_count=10,
        runtime_seconds=120.5,
    )
    assert s.manually_confirmed == 0
