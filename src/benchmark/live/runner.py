"""Bridge serialized live challenger execution to immutable result artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from benchmark.models import Finding

from .observations import LiveObservationStore, LivePRSnapshot
from .resource_lease import SqliteResourceLeaseStore
from .scheduler import LiveChallengerResult, LiveChallengerScheduler


class ResourceUnavailable(RuntimeError):
    """Raised when another worker currently owns the only local GPU lease."""


class LiveShadowRunner:
    """Run pending challengers under the shared GPU lease and retain their results."""

    def __init__(
        self,
        store: LiveObservationStore,
        scheduler: LiveChallengerScheduler,
        lease_store: SqliteResourceLeaseStore,
        *,
        worker_id: str,
        lease_ttl_seconds: float = 3600,
    ) -> None:
        self._store = store
        self._scheduler = scheduler
        self._lease_store = lease_store
        self._worker_id = worker_id
        self._lease_ttl_seconds = lease_ttl_seconds

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

        if not pending:
            return [existing[name] for name in challengers if name in existing]
        lease = self._lease_store.acquire(
            "local-94gb-gpu", self._worker_id, ttl_seconds=self._lease_ttl_seconds
        )
        if lease is None:
            raise ResourceUnavailable("local-94gb-gpu is leased by another worker")
        try:
            # Another worker may have finished some of these while we waited
            # for the lease; don't redo work it already recorded.
            for name in list(pending):
                recorded = self._store.load_challenger_result(observation, name)
                if recorded is not None:
                    existing[name] = recorded
                    del pending[name]

            attempts = self._scheduler.run(
                observation,
                pending,
                before_each=lambda: lease.renew(ttl_seconds=self._lease_ttl_seconds),
            )
            for attempt in attempts:
                result = LiveChallengerResult(
                    attempt=attempt,
                    findings=captured_findings.get(attempt.challenger) if attempt.state == "succeeded" else None,
                )
                existing[attempt.challenger] = self._store.record_challenger_result(
                    observation, result
                ).result
        finally:
            lease.release()

        return [existing[name] for name in challengers if name in existing]
