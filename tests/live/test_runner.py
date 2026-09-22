from __future__ import annotations

from benchmark.live import (
    LiveChallengerScheduler,
    LiveObservationStore,
    LivePRSnapshot,
    LiveShadowRunner,
)
from benchmark.models import Finding


def test_runs_a_challenger_through_the_scheduler_and_persists_its_result(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    store = LiveObservationStore(tmp_path)
    runner = LiveShadowRunner(store, LiveChallengerScheduler())

    results = runner.run(
        observation,
        {
            "gito": lambda _snapshot: [
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
            ]
        },
    )

    assert results[0].attempt.state == "succeeded"
    assert store.load_challenger_result(observation, "gito") == results[0]


def test_retains_a_failed_attempt_without_blocking_the_next_challenger(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    store = LiveObservationStore(tmp_path)
    runner = LiveShadowRunner(store, LiveChallengerScheduler())

    results = runner.run(
        observation,
        {"gito": _raise_endpoint_error, "pr-agent": lambda _snapshot: []},
    )

    assert [result.attempt.state for result in results] == ["failed", "succeeded"]
    assert results[0].findings is None
    assert results[1].findings == ()
    assert store.load_challenger_result(observation, "pr-agent") == results[1]


def _raise_endpoint_error(_snapshot: LivePRSnapshot) -> list[Finding]:
    raise RuntimeError("endpoint unavailable")
