from __future__ import annotations

from unittest.mock import patch

import pytest

from benchmark.live import (
    LiveChallengerScheduler,
    LiveObservationStore,
    LivePRSnapshot,
    LiveShadowRunner,
    ResourceLease,
    ResourceUnavailable,
    SqliteResourceLeaseStore,
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
    runner = LiveShadowRunner(
        store,
        LiveChallengerScheduler(),
        SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3"),
        worker_id="worker-a",
    )

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
    runner = LiveShadowRunner(
        store,
        LiveChallengerScheduler(),
        SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3"),
        worker_id="worker-a",
    )

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


def test_persists_the_result_before_releasing_the_lease(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    store = LiveObservationStore(tmp_path / "observations")
    runner = LiveShadowRunner(
        store,
        LiveChallengerScheduler(),
        SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3"),
        worker_id="worker-a",
    )
    seen_recorded_before_release: list[bool] = []
    original_release = ResourceLease.release

    def spy_release(self: ResourceLease) -> None:
        seen_recorded_before_release.append(
            store.load_challenger_result(observation, "gito") is not None
        )
        original_release(self)

    with patch.object(ResourceLease, "release", spy_release):
        runner.run(observation, {"gito": lambda _snapshot: []})

    assert seen_recorded_before_release == [True]


def test_renews_the_lease_between_challengers_and_stops_if_renewal_fails(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    store = LiveObservationStore(tmp_path / "observations")
    runner = LiveShadowRunner(
        store,
        LiveChallengerScheduler(),
        SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3"),
        worker_id="worker-a",
    )

    with patch.object(ResourceLease, "renew", return_value=False) as renew:
        results = runner.run(
            observation,
            {"gito": lambda _snapshot: [], "pr-agent": lambda _snapshot: []},
        )

    renew.assert_called_once()
    assert results == []
    assert store.load_challenger_result(observation, "gito") is None
    assert store.load_challenger_result(observation, "pr-agent") is None


def test_does_not_run_a_local_challenger_without_the_gpu_lease(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    lease_store = SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3")
    runner = LiveShadowRunner(
        LiveObservationStore(tmp_path / "observations"),
        LiveChallengerScheduler(),
        lease_store,
        worker_id="worker-b",
    )
    lease = lease_store.acquire("local-94gb-gpu", "worker-a", ttl_seconds=60)
    assert lease is not None

    with pytest.raises(ResourceUnavailable, match="local-94gb-gpu"):
        runner.run(observation, {"gito": lambda _snapshot: []})

    lease.release()
