"""Migration-runner control-flow tests (no real database — see test_runengine_infra.py for that)."""
from __future__ import annotations

from pathlib import Path

from benchmark.runengine.db import run_migrations


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn
        self._last_result: list[tuple[str]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self._conn.executed_sql.append(sql)
        if sql.strip().startswith("SELECT filename FROM schema_migrations"):
            self._last_result = [(name,) for name in sorted(self._conn.applied)]
        elif sql.strip().startswith("INSERT INTO schema_migrations"):
            assert params is not None
            self._conn.applied.add(params[0])

    def fetchall(self) -> list[tuple[str]]:
        return self._last_result


class _FakeConnection:
    def __init__(self, already_applied: set[str]) -> None:
        self.applied = set(already_applied)
        self.executed_sql: list[str] = []
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.committed = True


def _write_migration(directory: Path, filename: str, sql: str = "SELECT 1;") -> None:
    (directory / filename).write_text(sql)


def test_applies_migrations_in_order_and_records_them(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_initial.sql")
    _write_migration(tmp_path, "0002_second.sql")
    conn = _FakeConnection(already_applied=set())

    applied = run_migrations(conn, migrations_dir=tmp_path)

    assert applied == ["0001_initial.sql", "0002_second.sql"]
    assert conn.applied == {"0001_initial.sql", "0002_second.sql"}
    assert conn.committed is True


def test_skips_already_applied_migrations(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_initial.sql")
    _write_migration(tmp_path, "0002_second.sql")
    conn = _FakeConnection(already_applied={"0001_initial.sql"})

    applied = run_migrations(conn, migrations_dir=tmp_path)

    assert applied == ["0002_second.sql"]
    assert "0001_initial.sql" not in conn.executed_sql[0]


def test_no_pending_migrations_applies_nothing(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_initial.sql")
    conn = _FakeConnection(already_applied={"0001_initial.sql"})

    applied = run_migrations(conn, migrations_dir=tmp_path)

    assert applied == []
