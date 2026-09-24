"""FR-010/FR-011: per-candidate/suite/policy Score computation.

Every succeeded Attempt (including every repetition) is its own independent
sample; repetitions are never pre-reduced to a single per-item verdict before
aggregation (spec.md Clarifications). A plan with zero successful attempts
reports `value=None`/`sample_count=0` for quality metrics rather than
inventing a number; `completion_rate` is always numeric (data-model.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg

_QUALITY_METRICS = ("recall", "precision", "f1", "false_positive_rate", "duplicate_rate")


@dataclass(frozen=True)
class MetricValue:
    value: float | None
    sample_count: int
    range_min: float | None = None
    range_max: float | None = None


def compute_scores(
    conn: psycopg.Connection, *, plan_id: UUID, candidate_version_id: UUID
) -> dict[str, MetricValue]:
    """Aggregate quality and completion metrics from successful attempts."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, oracle_label_count, matched_gold_label_count FROM attempt "
            "WHERE plan_id = %s AND candidate_version_id = %s AND status = 'succeeded'",
            (plan_id, candidate_version_id),
        )
        succeeded = cur.fetchall()

        cur.execute(
            "SELECT count(*) FROM attempt WHERE plan_id = %s AND candidate_version_id = %s "
            "AND retry_of_attempt_id IS NULL",
            (plan_id, candidate_version_id),
        )
        (total_cells,) = cur.fetchone()
        cur.execute(
            "SELECT count(DISTINCT coalesce(retry_of_attempt_id, id)) FROM attempt "
            "WHERE plan_id = %s AND candidate_version_id = %s AND status = 'succeeded'",
            (plan_id, candidate_version_id),
        )
        (completed_cells,) = cur.fetchone()

        evaluations_by_attempt: dict[UUID, list[str]] = {}
        if succeeded:
            attempt_ids = [row[0] for row in succeeded]
            cur.execute(
                "SELECT attempt_id, outcome FROM evaluation WHERE attempt_id = ANY(%s)",
                (attempt_ids,),
            )
            for attempt_id, outcome in cur.fetchall():
                evaluations_by_attempt.setdefault(attempt_id, []).append(outcome)

    completion_rate = MetricValue(
        value=(completed_cells / total_cells) if total_cells else 0.0, sample_count=total_cells
    )
    if not succeeded:
        metrics: dict[str, MetricValue] = {
            name: MetricValue(value=None, sample_count=0) for name in _QUALITY_METRICS
        }
        metrics["completion_rate"] = completion_rate
        return metrics

    recalls: list[float] = []
    precisions: list[float] = []
    fp_rates: list[float] = []
    dup_rates: list[float] = []
    for attempt_id, oracle_count, matched_count in succeeded:
        recalls.append((matched_count / oracle_count) if oracle_count else 1.0)
        outcomes = evaluations_by_attempt.get(attempt_id, [])
        total = len(outcomes)
        if total == 0:
            precisions.append(1.0)
            fp_rates.append(0.0)
            dup_rates.append(0.0)
            continue
        precisions.append(sum(1 for o in outcomes if o == "matched") / total)
        fp_rates.append(sum(1 for o in outcomes if o == "false_positive") / total)
        dup_rates.append(sum(1 for o in outcomes if o == "duplicate") / total)
    f1s = [
        (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
        for p, r in zip(precisions, recalls, strict=True)
    ]

    def _aggregate(values: list[float]) -> MetricValue:
        """Summarize nonempty per-attempt values with their mean and range."""
        return MetricValue(
            value=sum(values) / len(values), sample_count=len(values),
            range_min=min(values), range_max=max(values),
        )

    return {
        "recall": _aggregate(recalls),
        "precision": _aggregate(precisions),
        "f1": _aggregate(f1s),
        "false_positive_rate": _aggregate(fp_rates),
        "duplicate_rate": _aggregate(dup_rates),
        "completion_rate": completion_rate,
    }


def compute_operational_metrics(
    conn: psycopg.Connection, *, plan_id: UUID, candidate_version_id: UUID
) -> dict[str, MetricValue]:
    """Queue wait and execution time, from succeeded attempts' own timestamps (FR-005/FR-011)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT queued_at, leased_at, started_at, finished_at FROM attempt "
            "WHERE plan_id = %s AND candidate_version_id = %s AND status = 'succeeded'",
            (plan_id, candidate_version_id),
        )
        rows = cur.fetchall()

    def _aggregate(values: list[float]) -> MetricValue:
        """Summarize timing samples or report that none were available."""
        if not values:
            return MetricValue(value=None, sample_count=0)
        return MetricValue(
            value=sum(values) / len(values), sample_count=len(values),
            range_min=min(values), range_max=max(values),
        )

    queue_waits = [
        (leased_at - queued_at).total_seconds()
        for queued_at, leased_at, _, _ in rows
        if queued_at is not None and leased_at is not None
    ]
    execution_times = [
        (finished_at - started_at).total_seconds()
        for _, _, started_at, finished_at in rows
        if started_at is not None and finished_at is not None
    ]
    return {
        "queue_wait_seconds": _aggregate(queue_waits),
        "execution_seconds": _aggregate(execution_times),
    }


def persist_scores(
    conn: psycopg.Connection,
    *,
    plan_id: UUID,
    candidate_version_id: UUID,
    suite_version_digest: str,
    score_policy_version: str,
    metrics: dict[str, MetricValue],
) -> None:
    """Upsert computed metrics for a candidate and plan."""
    with conn.cursor() as cur:
        for name, metric in metrics.items():
            cur.execute(
                """
                INSERT INTO score
                    (id, plan_id, candidate_version_id, suite_version_digest,
                     score_policy_version, metric_name, value, range_min, range_max, sample_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (plan_id, candidate_version_id, metric_name) DO UPDATE SET
                    value = EXCLUDED.value, range_min = EXCLUDED.range_min,
                    range_max = EXCLUDED.range_max, sample_count = EXCLUDED.sample_count,
                    computed_at = now()
                """,
                (
                    uuid4(), plan_id, candidate_version_id, suite_version_digest,
                    score_policy_version, name, metric.value, metric.range_min,
                    metric.range_max, metric.sample_count,
                ),
            )
    conn.commit()
