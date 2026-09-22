"""GitHub pull-request event adapter for immutable live shadow observations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from benchmark.models import LiveRepositoryIntegration

from .ingest import LivePRIngestor
from .observations import ObservationRecordResult

_OBSERVATION_ACTIONS = {"opened", "reopened", "synchronize"}


class PullRequestEventAdapter:
    """Accept opted-in GitHub PR events and preserve their delivered SHA pair."""

    def __init__(
        self,
        integrations: Mapping[str, LiveRepositoryIntegration],
        ingestor: LivePRIngestor,
    ) -> None:
        self._integrations = integrations
        self._ingestor = ingestor

    def handle(self, event_name: str, payload: Mapping[str, Any]) -> ObservationRecordResult | None:
        """Return an observation for supported opted-in PR events, otherwise ignore it."""
        if event_name != "pull_request" or payload.get("action") not in _OBSERVATION_ACTIONS:
            return None
        repository = _required_string(payload, "repository", "full_name")
        integration = self._integrations.get(repository)
        if integration is None or not integration.enabled:
            return None
        pr_number = payload.get("number")
        if not isinstance(pr_number, int) or pr_number <= 0:
            raise ValueError("GitHub pull_request event has no valid number")
        return self._ingestor.ingest_snapshot(
            integration,
            pr_number,
            base_sha=_required_string(payload, "pull_request", "base", "sha"),
            head_sha=_required_string(payload, "pull_request", "head", "sha"),
        )


def _required_string(payload: Mapping[str, Any], *path: str) -> str:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            raise ValueError(f"GitHub pull_request event is missing {'.'.join(path)}")
        current = current.get(key)
    if not isinstance(current, str) or not current:
        raise ValueError(f"GitHub pull_request event is missing {'.'.join(path)}")
    return current
