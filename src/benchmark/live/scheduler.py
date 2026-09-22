"""Serialized execution boundary for local live-review challengers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from threading import Lock
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .observations import LivePRSnapshot


class LiveChallengerAttempt(BaseModel):
    """The terminal record for one challenger on one immutable PR snapshot."""

    model_config = ConfigDict(frozen=True)

    challenger: str = Field(min_length=1)
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    state: Literal["succeeded", "failed"]
    duration_seconds: float = Field(ge=0.0)
    error: str | None = None


class LiveChallengerScheduler:
    """One-process serialized queue for local challengers sharing the GPU."""

    def __init__(self) -> None:
        self._lock = Lock()

    def run(
        self,
        snapshot: LivePRSnapshot,
        challengers: Mapping[str, Callable[[LivePRSnapshot], None]],
    ) -> list[LiveChallengerAttempt]:
        """Run requested challengers in stable order without cross-PR overlap."""
        with self._lock:
            attempts: list[LiveChallengerAttempt] = []
            canonical_order = [name for name in ("gito", "pr-agent") if name in challengers]
            remaining = sorted(set(challengers) - set(canonical_order))
            for challenger_name in [*canonical_order, *remaining]:
                attempts.append(self._run_one(challenger_name, challengers[challenger_name], snapshot))
            return attempts

    @staticmethod
    def _run_one(
        challenger_name: str,
        challenger: Callable[[LivePRSnapshot], None],
        snapshot: LivePRSnapshot,
    ) -> LiveChallengerAttempt:
        started_at = monotonic()
        try:
            challenger(snapshot)
        except Exception as error:  # noqa: BLE001
            return LiveChallengerAttempt(
                challenger=challenger_name,
                base_sha=snapshot.base_sha,
                head_sha=snapshot.head_sha,
                state="failed",
                duration_seconds=monotonic() - started_at,
                error=f"{type(error).__name__}: {error}",
            )
        return LiveChallengerAttempt(
            challenger=challenger_name,
            base_sha=snapshot.base_sha,
            head_sha=snapshot.head_sha,
            state="succeeded",
            duration_seconds=monotonic() - started_at,
        )
