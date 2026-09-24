"""FR-012: a candidate version whose capability probe hasn't passed cannot be
referenced by plan create."""
from __future__ import annotations

from uuid import uuid4

import pytest

from benchmark.runengine.candidate import CandidateNotUsable, CandidateVersion, require_passed
from benchmark.runengine.plan import PlanRequest, create_plan


def _candidate(status: str) -> CandidateVersion:
    return CandidateVersion(
        id=uuid4(), slug="gito", tool_version="1.0", package_digest="d" * 64,
        model_endpoint_config_hash="e" * 64, capability_probe_status=status,
    )


def test_require_passed_accepts_a_passed_probe() -> None:
    require_passed(_candidate("passed"))  # must not raise


def test_require_passed_rejects_pending() -> None:
    with pytest.raises(CandidateNotUsable):
        require_passed(_candidate("pending"))


def test_require_passed_rejects_failed() -> None:
    with pytest.raises(CandidateNotUsable):
        require_passed(_candidate("failed"))


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self._result = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        sql = sql.strip()
        if sql.startswith("SELECT id, slug, tool_version"):
            candidate = self._conn.candidates_by_id.get(params[0])
            self._result = (
                (
                    candidate.id, candidate.slug, candidate.tool_version,
                    candidate.package_digest, candidate.model_endpoint_config_hash,
                    candidate.capability_probe_status,
                )
                if candidate
                else None
            )
        elif sql.startswith("SELECT id, created_at FROM execution_plan"):
            self._result = None

    def fetchone(self):
        return self._result


class _FakeConnection:
    def __init__(self, candidates: list[CandidateVersion]) -> None:
        self.candidates_by_id = {c.id: c for c in candidates}

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        pass


def test_create_plan_rejects_a_not_yet_passed_candidate() -> None:
    pending_candidate = _candidate("pending")
    conn = _FakeConnection([pending_candidate])
    request = PlanRequest(
        suite_version_digest="a" * 64,
        candidate_version_ids=(pending_candidate.id,),
        repetitions=1, retry_cap=0, score_policy_version="review-v1-policy-1",
        created_by="haex",
    )

    with pytest.raises(CandidateNotUsable):
        create_plan(conn, request)
