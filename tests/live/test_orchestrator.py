from __future__ import annotations

from datetime import timedelta
from unittest.mock import Mock

from benchmark.live import (
    CodeRabbitBaselineCapture,
    LiveChallengerScheduler,
    LiveObservationStore,
    LivePRIngestor,
    LiveShadowRunner,
    SqliteResourceLeaseStore,
    run_live_shadow_review,
)
from benchmark.models import LiveRepositoryIntegration

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def _integration(**overrides) -> LiveRepositoryIntegration:
    return LiveRepositoryIntegration(
        owner="haexmas", name="holzi", enabled=True, baseline_wait_minutes=30, **overrides
    )


def _build(tmp_path, *, coderabbit_comments: list[dict]):
    store = LiveObservationStore(tmp_path / "observations")
    ingestor = LivePRIngestor(
        store,
        fetch_refs=lambda _o, _n, _pr: {"base_sha": BASE_SHA, "head_sha": HEAD_SHA},
        fetch_diff=lambda _o, _n, _b, _h: "diff content",
    )
    baseline_capture = CodeRabbitBaselineCapture(
        store, fetch_comments=lambda _repo, _pr: coderabbit_comments
    )
    runner = LiveShadowRunner(
        store,
        LiveChallengerScheduler(),
        SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3"),
        worker_id="worker-a",
    )
    return store, ingestor, baseline_capture, runner


def _coderabbit_comment() -> dict:
    return {
        "commit_id": HEAD_SHA,
        "user": {"login": "coderabbitai[bot]"},
        "id": 1,
        "path": "src/service.py",
        "line": 12,
        "body": "<!-- cr-indicator-types:potential_issue -->\n_bug_ | _major_ | _\n**Finding**\nDetails",
    }


def test_reaches_complete_once_the_baseline_window_closes_with_a_match(tmp_path) -> None:
    store, ingestor, baseline_capture, runner = _build(tmp_path, coderabbit_comments=[_coderabbit_comment()])
    integration = _integration()

    ingested_at = ingestor.ingest(integration, 27).observation.created_at
    observation = run_live_shadow_review(
        ingestor,
        baseline_capture,
        runner,
        store,
        integration,
        27,
        {"gito": lambda _snapshot: []},
        now=ingested_at + timedelta(minutes=31),
    )

    assert observation.state == "complete"


def test_stays_non_terminal_while_the_baseline_window_is_still_open(tmp_path) -> None:
    store, ingestor, baseline_capture, runner = _build(tmp_path, coderabbit_comments=[_coderabbit_comment()])
    integration = _integration()

    ingested_at = ingestor.ingest(integration, 27).observation.created_at
    observation = run_live_shadow_review(
        ingestor,
        baseline_capture,
        runner,
        store,
        integration,
        27,
        {"gito": lambda _snapshot: []},
        now=ingested_at + timedelta(minutes=5),
    )

    assert observation.state == "running_challengers"
    # The challenger still ran; only the terminal state is withheld.
    assert store.load_challenger_result(observation.snapshot, "gito") is not None


def test_reaches_baseline_incomplete_once_the_window_closes_with_no_match(tmp_path) -> None:
    store, ingestor, baseline_capture, runner = _build(tmp_path, coderabbit_comments=[])
    integration = _integration()

    ingested_at = ingestor.ingest(integration, 27).observation.created_at
    observation = run_live_shadow_review(
        ingestor,
        baseline_capture,
        runner,
        store,
        integration,
        27,
        {"gito": lambda _snapshot: []},
        now=ingested_at + timedelta(minutes=31),
    )

    assert observation.state == "baseline_incomplete"


def test_reaches_challenger_failed_even_when_the_baseline_is_present(tmp_path) -> None:
    store, ingestor, baseline_capture, runner = _build(tmp_path, coderabbit_comments=[_coderabbit_comment()])
    integration = _integration()

    def _failing(_snapshot):
        raise RuntimeError("endpoint unavailable")

    ingested_at = ingestor.ingest(integration, 27).observation.created_at
    observation = run_live_shadow_review(
        ingestor,
        baseline_capture,
        runner,
        store,
        integration,
        27,
        {"gito": _failing},
        now=ingested_at + timedelta(minutes=31),
    )

    assert observation.state == "challenger_failed"


def test_does_not_reopen_or_recapture_a_terminal_observation(tmp_path) -> None:
    comments: list[list[dict]] = [[]]
    store, ingestor, baseline_capture, runner = _build(tmp_path, coderabbit_comments=comments[0])
    integration = _integration()
    ingested_at = ingestor.ingest(integration, 27).observation.created_at
    first = run_live_shadow_review(
        ingestor,
        baseline_capture,
        runner,
        store,
        integration,
        27,
        {"gito": lambda _snapshot: []},
        now=ingested_at + timedelta(minutes=31),
    )
    assert first.state == "baseline_incomplete"

    calls = 0

    def unexpected_fetch(_repo: str, _pr: int) -> list[dict]:
        nonlocal calls
        calls += 1
        return [_coderabbit_comment()]

    late_capture = CodeRabbitBaselineCapture(store, fetch_comments=unexpected_fetch)
    second = run_live_shadow_review(
        ingestor,
        late_capture,
        runner,
        store,
        integration,
        27,
        {"gito": lambda _snapshot: []},
        now=ingested_at + timedelta(minutes=60),
    )

    assert second.state == "baseline_incomplete"
    assert calls == 0


def test_stays_running_when_a_requested_challenger_has_no_recorded_result(tmp_path) -> None:
    store, ingestor, baseline_capture, _runner = _build(
        tmp_path, coderabbit_comments=[_coderabbit_comment()]
    )
    integration = _integration()
    runner = Mock()
    runner.run.return_value = []
    ingested_at = ingestor.ingest(integration, 27).observation.created_at

    observation = run_live_shadow_review(
        ingestor,
        baseline_capture,
        runner,
        store,
        integration,
        27,
        {"gito": lambda _snapshot: []},
        now=ingested_at + timedelta(minutes=31),
    )

    assert observation.state == "running_challengers"
