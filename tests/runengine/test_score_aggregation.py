"""FR-010/FR-011: score aggregation from independent per-attempt samples.

Every repetition is its own sample (never pre-reduced to one per-item verdict);
a plan with zero successful attempts reports value=None/sample_count=0 for
quality metrics rather than inventing a number; completion_rate is always
numeric over the plan's expected work cells, retries counting once for their
original cell.
"""
from __future__ import annotations

from uuid import uuid4

from benchmark.runengine.scoring import compute_scores


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        """Initialize this test double with its simulated state."""
        self._conn = conn
        self._result: list | int | None = None

    def __enter__(self) -> _FakeCursor:
        """Enter the fake database context and return its cursor."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Leave the fake database context without suppressing exceptions."""
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        """Emulate the SQL operation needed by this test."""
        sql = " ".join(sql.split())
        if sql.startswith("SELECT id, oracle_label_count, matched_gold_label_count"):
            self._result = [
                (a.id, a.oracle_label_count, a.matched_gold_label_count)
                for a in self._conn.attempts
                if a.candidate_version_id == params[1] and a.status == "succeeded"
            ]
        elif "count(*) FROM attempt" in sql and "retry_of_attempt_id IS NULL" in sql:
            self._result = (
                sum(
                    1 for a in self._conn.attempts
                    if a.candidate_version_id == params[1] and a.retry_of_attempt_id is None
                ),
            )
        elif "count(DISTINCT coalesce" in sql:
            cell_ids = {
                a.retry_of_attempt_id or a.id
                for a in self._conn.attempts
                if a.candidate_version_id == params[1] and a.status == "succeeded"
            }
            self._result = (len(cell_ids),)
        elif sql.startswith("SELECT attempt_id, outcome FROM evaluation"):
            attempt_ids = set(params[0])
            self._result = [
                (e.attempt_id, e.outcome) for e in self._conn.evaluations
                if e.attempt_id in attempt_ids
            ]

    def fetchall(self) -> list:
        """Return the simulated multi-row query result."""
        return self._result or []

    def fetchone(self) -> tuple:
        """Return the simulated single-row query result."""
        return self._result


class _FakeAttempt:
    def __init__(self, candidate_version_id, status, oracle_count=0, matched_count=0, retry_of=None):
        """Initialize this test double with its simulated state."""
        self.id = uuid4()
        self.candidate_version_id = candidate_version_id
        self.status = status
        self.oracle_label_count = oracle_count
        self.matched_gold_label_count = matched_count
        self.retry_of_attempt_id = retry_of


class _FakeEvaluation:
    def __init__(self, attempt_id, outcome):
        """Initialize this test double with its simulated state."""
        self.attempt_id = attempt_id
        self.outcome = outcome


class _FakeConnection:
    def __init__(self, attempts: list[_FakeAttempt], evaluations: list[_FakeEvaluation]) -> None:
        """Initialize this test double with its simulated state."""
        self.attempts = attempts
        self.evaluations = evaluations

    def cursor(self) -> _FakeCursor:
        """Return a fake cursor bound to this connection."""
        return _FakeCursor(self)


def test_each_repetition_is_an_independent_sample_with_a_visible_range() -> None:
    """Verify each repetition is an independent sample with a visible range."""
    candidate = uuid4()
    a1 = _FakeAttempt(candidate, "succeeded", oracle_count=3, matched_count=1)
    a2 = _FakeAttempt(candidate, "succeeded", oracle_count=3, matched_count=2)
    a3 = _FakeAttempt(candidate, "succeeded", oracle_count=3, matched_count=3)
    conn = _FakeConnection([a1, a2, a3], [])

    metrics = compute_scores(conn, plan_id=uuid4(), candidate_version_id=candidate)

    assert metrics["recall"].sample_count == 3
    assert metrics["recall"].range_min == 1 / 3
    assert metrics["recall"].range_max == 1.0
    assert metrics["recall"].value == (1 / 3 + 2 / 3 + 1.0) / 3


def test_no_successful_attempts_reports_null_quality_metrics_not_zero() -> None:
    """Verify no successful attempts reports null quality metrics not zero."""
    candidate = uuid4()
    failed = _FakeAttempt(candidate, "failed")
    conn = _FakeConnection([failed], [])

    metrics = compute_scores(conn, plan_id=uuid4(), candidate_version_id=candidate)

    assert metrics["recall"].value is None
    assert metrics["recall"].sample_count == 0
    assert metrics["completion_rate"].value == 0.0
    assert metrics["completion_rate"].sample_count == 1


def test_completion_rate_counts_a_retry_chain_once_for_its_original_cell() -> None:
    """Verify completion rate counts a retry chain once for its original cell."""
    candidate = uuid4()
    original = _FakeAttempt(candidate, "failed")
    retry = _FakeAttempt(candidate, "succeeded", oracle_count=1, matched_count=1, retry_of=original.id)
    conn = _FakeConnection([original, retry], [])

    metrics = compute_scores(conn, plan_id=uuid4(), candidate_version_id=candidate)

    assert metrics["completion_rate"].sample_count == 1  # one logical cell, not two rows
    assert metrics["completion_rate"].value == 1.0


def test_precision_and_false_positive_rate_come_from_per_finding_evaluations() -> None:
    """Verify precision and false positive rate come from per finding evaluations."""
    candidate = uuid4()
    attempt = _FakeAttempt(candidate, "succeeded", oracle_count=1, matched_count=1)
    conn = _FakeConnection(
        [attempt],
        [
            _FakeEvaluation(attempt.id, "matched"),
            _FakeEvaluation(attempt.id, "false_positive"),
            _FakeEvaluation(attempt.id, "duplicate"),
        ],
    )

    metrics = compute_scores(conn, plan_id=uuid4(), candidate_version_id=candidate)

    assert metrics["precision"].value == 1 / 3
    assert metrics["false_positive_rate"].value == 1 / 3
    assert metrics["duplicate_rate"].value == 1 / 3
