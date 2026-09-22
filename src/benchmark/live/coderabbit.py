"""Capture a CodeRabbit baseline without mixing PR revisions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchmark.coderabbit.parser import parse_cr

from .observations import (
    CodeRabbitSnapshot,
    CodeRabbitSnapshotRecordResult,
    LiveObservationStore,
    LivePRSnapshot,
)


class CodeRabbitBaselineCapture:
    """Store only CodeRabbit items GitHub explicitly associates with one Head SHA."""

    def __init__(
        self,
        store: LiveObservationStore,
        fetch_comments: Callable[[str, int], list[dict[str, Any]]],
    ) -> None:
        self._store = store
        self._fetch_comments = fetch_comments

    def capture(self, observation: LivePRSnapshot) -> CodeRabbitSnapshotRecordResult | None:
        """Capture a matching review, or return ``None`` while CodeRabbit is unavailable."""
        comments = self._fetch_comments(observation.repository, observation.pr_number)
        matching_comments = [
            comment for comment in comments if comment.get("commit_id") == observation.head_sha
        ]
        if not matching_comments:
            return None
        baseline = CodeRabbitSnapshot(
            head_sha=observation.head_sha,
            findings=parse_cr(matching_comments),
        )
        return self._store.record_coderabbit_snapshot(observation, baseline)
