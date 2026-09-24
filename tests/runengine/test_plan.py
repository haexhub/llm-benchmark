"""FR-001: identical plan requests by the same actor return the same plan."""
from __future__ import annotations

from uuid import uuid4

import pytest

from benchmark.runengine.plan import PlanRequest, create_plan


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self._result: tuple | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        sql = sql.strip()
        if sql.startswith("SELECT id, slug, tool_version"):
            # create_plan's FR-012 gate: every candidate_version_id used in
            # this test module is treated as already probe-passed.
            (candidate_version_id,) = params
            self._result = (
                candidate_version_id, "gito", "1.0", "d" * 64, "e" * 64, "passed",
            )
        elif sql.startswith("SELECT id, created_at FROM execution_plan"):
            actor, key = params
            self._result = self._conn.plans_by_key.get((actor, key))
        elif sql.startswith("INSERT INTO execution_plan"):
            (
                plan_id, suite_digest, candidate_ids, repetitions, retry_cap,
                resource_profile, score_policy_version, comparison_axis, key,
                created_by, created_at,
            ) = params
            self._conn.plans_by_key[(created_by, key)] = (plan_id, created_at)
            self._conn.inserted_plans.append(params)

    def fetchone(self) -> tuple | None:
        return self._result


class _FakeConnection:
    def __init__(self) -> None:
        self.plans_by_key: dict[tuple[str, str], tuple] = {}
        self.inserted_plans: list[tuple] = []
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.committed = True


def _request(**overrides) -> PlanRequest:
    defaults = dict(
        suite_version_digest="d" * 64,
        candidate_version_ids=(uuid4(), uuid4()),
        repetitions=3,
        retry_cap=3,
        score_policy_version="review-v1-policy-1",
        created_by="haex",
    )
    defaults.update(overrides)
    return PlanRequest(**defaults)


def test_identical_request_returns_the_existing_plan() -> None:
    conn = _FakeConnection()
    request = _request()

    first = create_plan(conn, request)
    second = create_plan(conn, request)

    assert first.id == second.id
    assert len(conn.inserted_plans) == 1


def test_different_actor_gets_its_own_plan() -> None:
    conn = _FakeConnection()
    candidates = (uuid4(), uuid4())

    haex_plan = create_plan(conn, _request(candidate_version_ids=candidates, created_by="haex"))
    other_plan = create_plan(conn, _request(candidate_version_ids=candidates, created_by="other"))

    assert haex_plan.id != other_plan.id


def test_different_repetitions_is_a_different_plan() -> None:
    conn = _FakeConnection()

    plan_a = create_plan(conn, _request(repetitions=3))
    plan_b = create_plan(conn, _request(repetitions=5))

    assert plan_a.id != plan_b.id


def test_repetitions_must_be_positive() -> None:
    with pytest.raises(ValueError):
        _request(repetitions=0)
