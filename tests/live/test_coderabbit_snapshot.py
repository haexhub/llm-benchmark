from __future__ import annotations

import json

import pytest

from benchmark.live import (
    CodeRabbitBaselineCapture,
    CodeRabbitSnapshot,
    LiveObservationStore,
    LivePRSnapshot,
)
from benchmark.models import Finding


def test_captures_coderabbit_findings_only_for_the_observations_head_sha(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    baseline = CodeRabbitSnapshot(
        head_sha=observation.head_sha,
        findings=[
            Finding(
                tool="coderabbit",
                file="src/service.py",
                line_start=12,
                line_end=12,
                severity="major",
                category="bug",
                title="Validate the page size",
                body="A negative page size reaches the database query.",
            )
        ],
    )
    store = LiveObservationStore(tmp_path)
    store.record(observation)

    captured = store.record_coderabbit_snapshot(observation, baseline)

    assert captured.created is True
    assert captured.snapshot.head_sha == observation.head_sha
    artifact = json.loads(store.coderabbit_path(observation).read_text())
    assert artifact["head_sha"] == observation.head_sha
    assert artifact["findings"][0]["tool"] == "coderabbit"


def test_rejects_a_challenger_finding_from_a_coderabbit_snapshot() -> None:
    with pytest.raises(ValueError, match="CodeRabbit findings"):
        CodeRabbitSnapshot(
            head_sha="b" * 40,
            findings=[
                Finding(
                    tool="gito",
                    file="src/service.py",
                    line_start=12,
                    line_end=12,
                    severity="major",
                    category="bug",
                    title="Validate the page size",
                    body="A negative page size reaches the database query.",
                )
            ],
        )


def test_rejects_a_coderabbit_snapshot_for_a_different_pr_head(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    baseline = CodeRabbitSnapshot(head_sha="d" * 40)

    with pytest.raises(ValueError, match="Head SHA does not match"):
        LiveObservationStore(tmp_path).record_coderabbit_snapshot(observation, baseline)


def test_captures_only_coderabbit_comments_for_the_observations_head(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    matching = {
        "commit_id": observation.head_sha,
        "user": {"login": "coderabbitai[bot]"},
        "id": 1,
        "path": "src/service.py",
        "line": 12,
        "body": "<!-- cr-indicator-types:potential_issue -->\n_bug_ | _major_ | _\n**Valid finding**\nDetails",
    }
    stale = {**matching, "commit_id": "d" * 40, "id": 2, "body": matching["body"].replace("Valid", "Stale")}
    capture = CodeRabbitBaselineCapture(
        LiveObservationStore(tmp_path),
        fetch_comments=lambda _repo, _pr: [stale, matching],
    )

    result = capture.capture(observation, elapsed_minutes=30, wait_minutes=30)

    assert result.status == "captured"
    assert [finding.title for finding in result.result.snapshot.findings] == ["Valid finding"]


def test_ignores_a_matching_head_comment_from_another_author(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    spoofed = {
        "commit_id": observation.head_sha,
        "user": {"login": "someone-else"},
        "id": 1,
        "path": "src/service.py",
        "line": 12,
        "body": "<!-- cr-indicator-types:potential_issue -->\n_bug_ | _major_ | _\n**Spoofed finding**\nDetails",
    }
    capture = CodeRabbitBaselineCapture(
        LiveObservationStore(tmp_path),
        fetch_comments=lambda _repo, _pr: [spoofed],
    )

    result = capture.capture(observation, elapsed_minutes=30, wait_minutes=30)

    assert result.status == "unavailable"


def test_keeps_the_baseline_unavailable_when_no_comment_matches_the_head(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    capture = CodeRabbitBaselineCapture(
        LiveObservationStore(tmp_path),
        fetch_comments=lambda _repo, _pr: [{"commit_id": "d" * 40}],
    )

    result = capture.capture(observation, elapsed_minutes=30, wait_minutes=30)

    assert result.status == "unavailable"


def test_waits_for_the_full_window_before_checking_github_at_all(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )

    def _fail(_repo: str, _pr: int) -> list[dict]:
        raise AssertionError("must not check GitHub before the wait window closes")

    capture = CodeRabbitBaselineCapture(LiveObservationStore(tmp_path), fetch_comments=_fail)

    result = capture.capture(observation, elapsed_minutes=5, wait_minutes=30)

    assert result.status == "waiting"
    assert result.result is None
