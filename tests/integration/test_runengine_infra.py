"""db-marked: needs `docker compose up -d postgres minio` (quickstart.md)."""
from __future__ import annotations

import pytest

from benchmark.runengine.artifacts import ArtifactStore
from benchmark.runengine.db import connect, run_migrations


@pytest.mark.db
def test_migrations_apply_against_real_postgres() -> None:
    conn = connect()
    try:
        applied = run_migrations(conn)
        assert "0001_initial.sql" in applied
        again = run_migrations(conn)
        assert again == []
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.execution_plan')")
            assert cur.fetchone()[0] == "execution_plan"
    finally:
        conn.close()


@pytest.mark.db
def test_artifact_store_round_trips_a_blob() -> None:
    store = ArtifactStore()
    store.ensure_bucket()
    stored = store.put(b"hello run engine", content_type="text/plain")
    assert len(stored.sha256) == 64
    assert store.get(stored.sha256) == b"hello run engine"
