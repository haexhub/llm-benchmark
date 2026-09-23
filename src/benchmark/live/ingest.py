"""Capture enabled GitHub PR events as immutable local shadow-review inputs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from benchmark.models import LiveRepositoryIntegration

from .observations import LiveObservationStore, LivePRSnapshot, ObservationRecordResult


class LivePRIngestor:
    """Bind event-time Base/Head refs and diff content to one observation."""

    def __init__(
        self,
        store: LiveObservationStore,
        *,
        fetch_refs: Callable[[str, str, int], dict[str, str]],
        fetch_diff: Callable[[str, str, str, str], str],
    ) -> None:
        self._store = store
        self._fetch_refs = fetch_refs
        self._fetch_diff = fetch_diff

    def ingest(self, integration: LiveRepositoryIntegration, pr_number: int) -> ObservationRecordResult:
        """Capture an enabled PR exactly once using its event-time revision identity."""
        if not integration.enabled:
            raise ValueError(f"Live PR shadow review is not enabled for {integration.slug}")
        refs = self._fetch_refs(integration.owner, integration.name, pr_number)
        return self.ingest_snapshot(
            integration,
            pr_number,
            base_sha=refs["base_sha"],
            head_sha=refs["head_sha"],
        )

    def ingest_snapshot(
        self,
        integration: LiveRepositoryIntegration,
        pr_number: int,
        *,
        base_sha: str,
        head_sha: str,
    ) -> ObservationRecordResult:
        """Persist an event-supplied revision without consulting a mutable PR ref."""
        if not integration.enabled:
            raise ValueError(f"Live PR shadow review is not enabled for {integration.slug}")
        diff = self._fetch_diff(integration.owner, integration.name, base_sha, head_sha)
        snapshot = LivePRSnapshot(
            repository=integration.slug,
            pr_number=pr_number,
            base_sha=base_sha,
            head_sha=head_sha,
            diff_sha256=hashlib.sha256(diff.encode()).hexdigest(),
        )
        return self._store.record_with_diff(snapshot, diff)
