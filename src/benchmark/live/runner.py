"""Bridge serialized live challenger execution to immutable result artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from benchmark.models import Finding

from .observations import LiveObservationStore, LivePRSnapshot
from .scheduler import LiveChallengerResult, LiveChallengerScheduler


class LiveShadowRunner:
    """Run pending challengers serially and retain terminal results for one snapshot."""

    def __init__(self, store: LiveObservationStore, scheduler: LiveChallengerScheduler) -> None:
        self._store = store
        self._scheduler = scheduler

    def run(
        self,
        observation: LivePRSnapshot,
        challengers: Mapping[str, Callable[[LivePRSnapshot], list[Finding]]],
    ) -> list[LiveChallengerResult]:
        """Never rerun a challenger already recorded for this immutable revision."""
        existing: dict[str, LiveChallengerResult] = {}
        pending: dict[str, Callable[[LivePRSnapshot], None]] = {}
        captured_findings: dict[str, tuple[Finding, ...]] = {}
        for name, challenger in challengers.items():
            recorded = self._store.load_challenger_result(observation, name)
            if recorded is not None:
                existing[name] = recorded
                continue

            def capture(snapshot: LivePRSnapshot, *, _name: str = name, _challenger=challenger) -> None:
                captured_findings[_name] = tuple(_challenger(snapshot))

            pending[name] = capture

        attempts = self._scheduler.run(observation, pending) if pending else []
        for attempt in attempts:
            result = LiveChallengerResult(
                attempt=attempt,
                findings=captured_findings.get(attempt.challenger) if attempt.state == "succeeded" else None,
            )
            existing[attempt.challenger] = self._store.record_challenger_result(
                observation, result
            ).result

        return [existing[name] for name in challengers if name in existing]
