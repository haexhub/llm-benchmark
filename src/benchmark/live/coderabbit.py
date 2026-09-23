"""Capture a CodeRabbit baseline without mixing PR revisions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from benchmark.coderabbit.parser import parse_cr
from benchmark.github.fetch import CR_BOT_LOGIN

from .observations import (
    CodeRabbitSnapshot,
    CodeRabbitSnapshotRecordResult,
    LiveObservationStore,
    LivePRSnapshot,
)


class CodeRabbitBaselineAttempt(BaseModel):
    """The outcome of one baseline-capture attempt for one immutable revision."""

    model_config = ConfigDict(frozen=True)

    status: Literal["captured", "waiting", "unavailable"]
    result: CodeRabbitSnapshotRecordResult | None = None


class CodeRabbitBaselineCapture:
    """Store only CodeRabbit items GitHub explicitly associates with one Head SHA."""

    def __init__(
        self,
        store: LiveObservationStore,
        fetch_comments: Callable[[str, int], list[dict[str, Any]]],
    ) -> None:
        self._store = store
        self._fetch_comments = fetch_comments

    def capture(
        self, observation: LivePRSnapshot, *, elapsed_minutes: float, wait_minutes: int
    ) -> CodeRabbitBaselineAttempt:
        """Never finalize a baseline before its wait window closes.

        Comments can arrive incrementally over several minutes; treating the
        first match as final would persist a partial finding set (the store is
        write-once). Until ``elapsed_minutes`` reaches ``wait_minutes`` this
        returns ``waiting`` without even checking GitHub.
        """
        if elapsed_minutes < wait_minutes:
            return CodeRabbitBaselineAttempt(status="waiting")
        comments = self._fetch_comments(observation.repository, observation.pr_number)
        matching_comments = [
            comment
            for comment in comments
            if comment.get("commit_id") == observation.head_sha
            and (comment.get("user") or {}).get("login") == CR_BOT_LOGIN
        ]
        if not matching_comments:
            return CodeRabbitBaselineAttempt(status="unavailable")
        baseline = CodeRabbitSnapshot(
            head_sha=observation.head_sha,
            findings=parse_cr(matching_comments),
        )
        result = self._store.record_coderabbit_snapshot(observation, baseline)
        return CodeRabbitBaselineAttempt(status="captured", result=result)
