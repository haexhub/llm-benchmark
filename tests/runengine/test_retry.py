"""FR-013a/FR-013, research.md R9: transient-vs-non-transient failure classification."""
from __future__ import annotations

from benchmark.runengine.retry import classify_failure, should_retry


def test_timeout_is_transient() -> None:
    assert classify_failure(
        timed_out=True, returncode=-9, stdout="", stderr="", schema_drift=False
    ) == "transient"


def test_empty_output_nonzero_exit_is_transient() -> None:
    assert classify_failure(
        timed_out=False, returncode=1, stdout="", stderr="", schema_drift=False
    ) == "transient"


def test_connection_refused_text_is_transient() -> None:
    assert classify_failure(
        timed_out=False, returncode=1, stdout="", stderr="Connection refused",
        schema_drift=False,
    ) == "transient"


def test_schema_drift_is_never_transient_even_if_it_looks_like_a_timeout() -> None:
    assert classify_failure(
        timed_out=True, returncode=0, stdout="", stderr="timed out waiting for judge",
        schema_drift=True,
    ) == "non_transient"


def test_normal_tool_error_with_output_is_non_transient() -> None:
    assert classify_failure(
        timed_out=False, returncode=1, stdout="", stderr="unknown flag --foo",
        schema_drift=False,
    ) == "non_transient"


def test_should_retry_below_cap() -> None:
    assert should_retry(retry_count=1, retry_cap=3) is True


def test_should_not_retry_at_cap() -> None:
    assert should_retry(retry_count=3, retry_cap=3) is False


def test_should_not_retry_when_cap_is_zero() -> None:
    assert should_retry(retry_count=0, retry_cap=0) is False
