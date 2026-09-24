"""Transient-vs-non-transient failure classification and retry-cap check (FR-013a, research.md R9)."""

from __future__ import annotations

from typing import Literal

FailureClass = Literal["transient", "non_transient"]

_TRANSIENT_MARKERS = (
    "connection refused",
    "connection reset",
    "connection aborted",
    "timed out",
    "timeouterror",
    "readtimeout",
    "connecttimeout",
    "temporary failure in name resolution",
    "name or service not known",
)


def classify_failure(
    *, timed_out: bool, returncode: int, stdout: str, stderr: str, schema_drift: bool
) -> FailureClass:
    """Decide whether a failed Attempt is worth retrying automatically.

    Schema drift is never transient — retrying would reproduce the same
    unparseable output deterministically (FR-013).
    """
    if schema_drift:
        return "non_transient"
    if timed_out:
        return "transient"
    if returncode != 0 and not stdout.strip() and not stderr.strip():
        return "transient"
    combined = f"{stdout}\n{stderr}".lower()
    if any(marker in combined for marker in _TRANSIENT_MARKERS):
        return "transient"
    return "non_transient"


def should_retry(*, retry_count: int, retry_cap: int) -> bool:
    """`retry_count` is how many retries already exist for this cell (excluding the original)."""
    return retry_count < retry_cap
