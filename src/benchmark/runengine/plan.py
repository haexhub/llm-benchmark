"""ExecutionPlan creation with idempotency scoped to the creating actor (FR-001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import psycopg

COMPARISON_AXIS = "end_to_end_agent"
RESOURCE_PROFILE = "local-94gb-gpu"


@dataclass(frozen=True)
class PlanRequest:
    suite_version_digest: str
    candidate_version_ids: tuple[UUID, ...]
    repetitions: int
    retry_cap: int
    score_policy_version: str
    created_by: str

    def __post_init__(self) -> None:
        """Reject requests with invalid repetition or retry limits."""
        if self.repetitions < 1:
            raise ValueError("repetitions must be >= 1")
        if self.retry_cap < 0:
            raise ValueError("retry_cap must be >= 0")
        if not self.candidate_version_ids:
            raise ValueError("at least one candidate_version_id is required")


@dataclass(frozen=True)
class ExecutionPlan:
    id: UUID
    suite_version_digest: str
    candidate_version_ids: tuple[UUID, ...]
    repetitions: int
    retry_cap: int
    resource_profile: str
    score_policy_version: str
    comparison_axis: str
    created_by: str
    created_at: datetime


def idempotency_key(request: PlanRequest) -> str:
    """Hash the actor and normalized plan axes into a stable request key."""
    normalized = "|".join(
        [
            request.suite_version_digest,
            ",".join(sorted(str(c) for c in request.candidate_version_ids)),
            str(request.repetitions),
            str(request.retry_cap),
            request.score_policy_version,
        ]
    )
    return sha256(f"{request.created_by}:{normalized}".encode()).hexdigest()


def create_plan(conn: psycopg.Connection, request: PlanRequest) -> ExecutionPlan:
    """Return the actor's existing plan for an identical request, or create a new one.

    Rejects any request referencing a candidate_version whose capability probe
    hasn't passed (FR-012) — checked even on the idempotent-return path, so a
    candidate that regresses after a plan was already created can't silently
    stay referenced by a *new* identical request either.
    """
    from benchmark.runengine.candidate import get_candidate, require_passed

    for candidate_version_id in request.candidate_version_ids:
        candidate = get_candidate(conn, candidate_version_id)
        if candidate is None:
            raise ValueError(f"Unknown candidate_version: {candidate_version_id}")
        require_passed(candidate)

    key = idempotency_key(request)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO execution_plan
                (id, suite_version_digest, candidate_version_ids, repetitions, retry_cap,
                 resource_profile, score_policy_version, comparison_axis, idempotency_key,
                 created_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (created_by, idempotency_key) DO NOTHING
            """,
            (
                uuid4(), request.suite_version_digest, list(request.candidate_version_ids),
                request.repetitions, request.retry_cap, RESOURCE_PROFILE,
                request.score_policy_version, COMPARISON_AXIS, key, request.created_by,
                datetime.now(UTC),
            ),
        )
        cur.execute(
            "SELECT id, created_at FROM execution_plan WHERE created_by = %s AND idempotency_key = %s",
            (request.created_by, key),
        )
        plan_id, created_at = cur.fetchone()
    conn.commit()
    return ExecutionPlan(
        id=plan_id,
        suite_version_digest=request.suite_version_digest,
        candidate_version_ids=request.candidate_version_ids,
        repetitions=request.repetitions,
        retry_cap=request.retry_cap,
        resource_profile=RESOURCE_PROFILE,
        score_policy_version=request.score_policy_version,
        comparison_axis=COMPARISON_AXIS,
        created_by=request.created_by,
        created_at=created_at,
    )
