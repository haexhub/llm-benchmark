"""FR-012: a candidate version whose capability probe hasn't passed cannot be
referenced by plan create."""
from __future__ import annotations

from uuid import uuid4

import pytest

from benchmark.runengine import candidate as candidate_module
from benchmark.runengine.candidate import CandidateNotUsable, CandidateVersion, require_passed
from benchmark.runengine.plan import PlanRequest, create_plan


def _candidate(status: str) -> CandidateVersion:
    """Build a candidate version with the requested probe status."""
    return CandidateVersion(
        id=uuid4(), slug="gito", tool_version="1.0", package_digest="d" * 64,
        model_endpoint_config_hash="e" * 64, capability_probe_status=status,
    )


def test_require_passed_accepts_a_passed_probe() -> None:
    """Verify require passed accepts a passed probe."""
    require_passed(_candidate("passed"))  # must not raise


def test_require_passed_rejects_pending() -> None:
    """Verify require passed rejects pending."""
    with pytest.raises(CandidateNotUsable):
        require_passed(_candidate("pending"))


def test_require_passed_rejects_failed() -> None:
    """Verify require passed rejects failed."""
    with pytest.raises(CandidateNotUsable):
        require_passed(_candidate("failed"))


def test_capability_probe_uses_the_registered_tool_version(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_run(command, **kwargs):
        captured.append(command)
        return type("Completed", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(candidate_module.subprocess, "run", fake_run)

    assert candidate_module.run_capability_probe("gito", "1.2.3")[0] == "passed"
    assert "gito.bot==1.2.3" in captured[0]


def test_capability_probe_records_a_missing_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_launcher(command, **kwargs):
        raise FileNotFoundError("uv")

    monkeypatch.setattr(candidate_module.subprocess, "run", missing_launcher)

    status, result = candidate_module.run_capability_probe("gito", "1.2.3")

    assert status == "failed"
    assert result["error"] == "launch_failed"


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        """Initialize this test double with its simulated state."""
        self._conn = conn
        self._result = None

    def __enter__(self) -> _FakeCursor:
        """Enter the fake database context and return its cursor."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Leave the fake database context without suppressing exceptions."""
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        """Emulate the SQL operation needed by this test."""
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
        """Return the simulated single-row query result."""
        return self._result


class _FakeConnection:
    def __init__(self, candidates: list[CandidateVersion]) -> None:
        """Initialize this test double with its simulated state."""
        self.candidates_by_id = {c.id: c for c in candidates}

    def cursor(self) -> _FakeCursor:
        """Return a fake cursor bound to this connection."""
        return _FakeCursor(self)

    def commit(self) -> None:
        """Accept a commit without writing to a database."""
        pass


def test_create_plan_rejects_a_not_yet_passed_candidate() -> None:
    """Verify create plan rejects a not yet passed candidate."""
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
