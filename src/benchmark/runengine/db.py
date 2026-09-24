"""PostgreSQL connection helper and migration runner for the Run Engine catalogue."""

from __future__ import annotations

from pathlib import Path

import psycopg

from benchmark.config import require_env

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_SCHEMA_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def connect() -> psycopg.Connection:
    """Open a connection to `RUNENGINE_DATABASE_URL`."""
    return psycopg.connect(require_env("RUNENGINE_DATABASE_URL"))


def run_migrations(conn: psycopg.Connection, *, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every not-yet-applied `NNNN_*.sql` file in order; return newly-applied filenames."""
    with conn.cursor() as cur:
        cur.execute(_SCHEMA_MIGRATIONS_TABLE)
        cur.execute("SELECT filename FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

    newly_applied: list[str] = []
    for migration_file in sorted(migrations_dir.glob("*.sql")):
        if migration_file.name in applied:
            continue
        with conn.cursor() as cur:
            cur.execute(migration_file.read_text())
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (migration_file.name,)
            )
        newly_applied.append(migration_file.name)
    conn.commit()
    return newly_applied
