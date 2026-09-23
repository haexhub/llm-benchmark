"""Drive one immutable PR revision from ingest through a terminal lifecycle state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from benchmark.models import Finding, LiveRepositoryIntegration

from .coderabbit import CodeRabbitBaselineCapture
from .ingest import LivePRIngestor
from .observations import LiveObservationStore, LivePRObservation, LivePRSnapshot
from .runner import LiveShadowRunner

_TERMINAL_STATES = frozenset({"complete", "baseline_incomplete", "challenger_failed"})


def run_live_shadow_review(
    ingestor: LivePRIngestor,
    baseline_capture: CodeRabbitBaselineCapture,
    runner: LiveShadowRunner,
    store: LiveObservationStore,
    integration: LiveRepositoryIntegration,
    pr_number: int,
    challengers: Mapping[str, Callable[[LivePRSnapshot], list[Finding]]],
    *,
    now: datetime,
) -> LivePRObservation:
    """Advance one PR revision as far as currently possible; safe to call repeatedly.

    Ingest, baseline capture and challenger execution are all idempotent, so a
    later call on the same revision only performs whatever work is still
    pending and re-derives the lifecycle state from what is now on record.
    """
    ingested = ingestor.ingest(integration, pr_number)
    observation = ingested.observation
    snapshot = observation.snapshot

    if observation.state in _TERMINAL_STATES:
        return observation

    if observation.state == "queued":
        observation = store.transition_state(snapshot, "running_challengers")

    elapsed_minutes = (now - observation.created_at).total_seconds() / 60
    baseline_attempt = baseline_capture.capture(
        snapshot,
        elapsed_minutes=elapsed_minutes,
        wait_minutes=integration.baseline_wait_minutes,
    )

    results = runner.run(snapshot, challengers)

    recorded_challengers = {result.attempt.challenger for result in results}
    if baseline_attempt.status == "waiting" or set(challengers) - recorded_challengers:
        # Challengers may already be done, but the baseline window hasn't
        # closed, or a challenger has not recorded a result yet; stay
        # non-terminal until a later call resolves it.
        return observation

    if any(result.attempt.state == "failed" for result in results):
        final_state = "challenger_failed"
    elif baseline_attempt.status == "unavailable":
        final_state = "baseline_incomplete"
    else:
        final_state = "complete"

    return store.transition_state(snapshot, final_state)
