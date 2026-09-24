"""US2: of several attempts contending for local-94gb-gpu, only one executes at a time.

Uses the real SqliteResourceLeaseStore (a local file, no external service —
this is a hermetic unit test, not `-m db`).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from benchmark.live import SqliteResourceLeaseStore
from benchmark.runengine.attempts import RESOURCE_NAME, run_attempt


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        """Initialize this test double with its simulated state."""
        self._conn = conn

    def __enter__(self) -> _FakeCursor:
        """Enter the fake database context and return its cursor."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Leave the fake database context without suppressing exceptions."""
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        """Emulate the SQL operation needed by this test."""
        self._conn.executed.append((sql.strip().split()[0], params))

    def fetchone(self) -> None:
        """Return the simulated single-row query result."""
        return None


class _FakeConnection:
    def __init__(self) -> None:
        """Initialize this test double with its simulated state."""
        self.executed: list[tuple] = []

    def cursor(self) -> _FakeCursor:
        """Return a fake cursor bound to this connection."""
        return _FakeCursor(self)

    def commit(self) -> None:
        """Accept a commit without writing to a database."""
        pass


def _never_called(**kwargs):
    """Fail if candidate execution occurs while the lease is unavailable."""
    raise AssertionError("executor must not run while the lease is held elsewhere")


def test_run_attempt_returns_none_and_never_executes_when_lease_is_busy(tmp_path: Path) -> None:
    """Verify run attempt returns none and never executes when lease is busy."""
    runs_dir = tmp_path / "runs"
    other_worker_store = SqliteResourceLeaseStore(runs_dir / "run-engine.sqlite3")
    lease = other_worker_store.acquire(RESOURCE_NAME, "other-worker", ttl_seconds=60)
    assert lease is not None

    conn = _FakeConnection()
    outcome = run_attempt(
        conn, store=object(), attempt_id=uuid4(), corpus_root=tmp_path, item_id="demo-item",
        candidate_slug="gito", model="m", config_hash="c" * 64,
        workspace_root=tmp_path / "workspaces", runs_dir=runs_dir,
        executor=_never_called,
    )

    assert outcome is None
    assert conn.executed == []  # no status transition attempted either


def test_second_worker_can_acquire_after_the_first_releases(tmp_path: Path) -> None:
    """Verify second worker can acquire after the first releases."""
    runs_dir = tmp_path / "runs"
    store_a = SqliteResourceLeaseStore(runs_dir / "run-engine.sqlite3")
    store_b = SqliteResourceLeaseStore(runs_dir / "run-engine.sqlite3")

    lease_a = store_a.acquire(RESOURCE_NAME, "worker-a", ttl_seconds=60)
    assert lease_a is not None
    assert store_b.acquire(RESOURCE_NAME, "worker-b", ttl_seconds=60) is None

    lease_a.release()

    assert store_b.acquire(RESOURCE_NAME, "worker-b", ttl_seconds=60) is not None
