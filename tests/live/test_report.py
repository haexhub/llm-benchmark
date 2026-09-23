from __future__ import annotations

from benchmark.live import (
    CodeRabbitSnapshot,
    LiveChallengerAttempt,
    LiveChallengerResult,
    LiveObservationStore,
    LivePRSnapshot,
)
from benchmark.live.report import render_live_observation, render_stored_live_observation
from benchmark.models import Finding


def test_renders_a_private_operational_three_way_observation() -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    baseline = CodeRabbitSnapshot(head_sha=observation.head_sha, findings=[_finding("coderabbit", "Baseline finding")])
    gito = LiveChallengerResult(
        attempt=LiveChallengerAttempt(
            challenger="gito",
            base_sha=observation.base_sha,
            head_sha=observation.head_sha,
            state="succeeded",
            duration_seconds=12.5,
        ),
        findings=[_finding("gito", "gito finding")],
    )
    pr_agent = LiveChallengerResult(
        attempt=LiveChallengerAttempt(
            challenger="pr-agent",
            base_sha=observation.base_sha,
            head_sha=observation.head_sha,
            state="failed",
            duration_seconds=1.5,
            error="RuntimeError: endpoint unavailable",
        ),
    )

    markdown = render_live_observation(observation, baseline, {"gito": gito, "pr-agent": pr_agent})

    assert "Operational only — not a Gold score" in markdown
    assert observation.head_sha in markdown
    assert "Baseline finding" in markdown
    assert "gito finding" in markdown
    assert "pr-agent: failed" in markdown
    assert "endpoint unavailable" in markdown


def test_renders_a_persisted_observation_without_retrieving_mutable_pr_data(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    store = LiveObservationStore(tmp_path)
    store.record_coderabbit_snapshot(
        observation, CodeRabbitSnapshot(head_sha=observation.head_sha, findings=[])
    )
    store.record_challenger_result(
        observation,
        LiveChallengerResult(
            attempt=LiveChallengerAttempt(
                challenger="gito",
                base_sha=observation.base_sha,
                head_sha=observation.head_sha,
                state="succeeded",
                duration_seconds=12.5,
            ),
            findings=[],
        ),
    )

    markdown = render_stored_live_observation(store, observation)

    assert "CodeRabbit baseline" in markdown
    assert "gito: succeeded" in markdown
    assert "pr-agent: not run" in markdown


def _finding(tool: str, title: str) -> Finding:
    return Finding(
        tool=tool,
        file="src/service.py",
        line_start=12,
        line_end=12,
        severity="major",
        category="bug",
        title=title,
        body="A negative page size reaches the database query.",
    )
