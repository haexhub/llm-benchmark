"""Serialized execution boundary for local live-review challengers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from benchmark.models import Finding

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


class LiveChallengerResult(BaseModel):
    """One terminal attempt with findings, or an explicit failure without them."""

    model_config = ConfigDict(frozen=True)

    attempt: LiveChallengerAttempt
    findings: tuple[Finding, ...] | None = None

    @model_validator(mode="after")
    def _findings_match_the_terminal_attempt(self) -> LiveChallengerResult:
        if self.attempt.state == "succeeded" and self.findings is None:
            raise ValueError("A successful challenger attempt requires findings, including an empty set")
        if self.attempt.state == "failed" and self.findings is not None:
            raise ValueError("A failed challenger attempt cannot be represented as an empty review")
        if self.findings and any(finding.tool != self.attempt.challenger for finding in self.findings):
            raise ValueError("Challenger findings must belong to the attempt's challenger")
        return self


class ChallengerResultRecordResult(BaseModel):
    """Whether a challenger result was new or an idempotent replay."""

    model_config = ConfigDict(frozen=True)

    result: LiveChallengerResult
    created: bool


class LiveChallengerScheduler:
    """Execute a worker's leased challengers in a deterministic order."""

    def run(
        self,
        snapshot: LivePRSnapshot,
        challengers: Mapping[str, Callable[[LivePRSnapshot], None]],
        *,
        before_each: Callable[[], bool] | None = None,
    ) -> list[LiveChallengerAttempt]:
        """Run requested challengers in stable order under the caller's resource lease.

        ``before_each``, when given, is called before every challenger; if it
        returns false (e.g. a lease renewal failed), no further challengers run.
        """
        attempts: list[LiveChallengerAttempt] = []
        canonical_order = [name for name in ("gito", "pr-agent") if name in challengers]
        remaining = sorted(set(challengers) - set(canonical_order))
        for challenger_name in [*canonical_order, *remaining]:
            if before_each is not None and not before_each():
                break
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
