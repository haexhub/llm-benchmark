"""US2: a runengine batch Attempt and a feature-004 live-challenger attempt must
never execute concurrently — both acquire from the same SqliteResourceLeaseStore
and `local-94gb-gpu` resource key (research.md R3). Hermetic: real SQLite file,
no Postgres/MinIO needed, so no `-m db` marker despite the "db-marked" wording
in tasks.md's T028 (that wording predates checking what the marker actually gates).
"""
from __future__ import annotations

from pathlib import Path

from benchmark.live import SqliteResourceLeaseStore
from benchmark.runengine.attempts import RESOURCE_NAME


def test_runengine_and_live_challenger_share_one_lease(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    lease_file = runs_dir / "run-engine.sqlite3"

    # Simulates benchmark.runengine.attempts.run_attempt's internal acquire().
    runengine_store = SqliteResourceLeaseStore(lease_file)
    runengine_lease = runengine_store.acquire(RESOURCE_NAME, "runengine-worker", ttl_seconds=3600)
    assert runengine_lease is not None

    # Simulates benchmark.live.runner.LiveShadowRunner.run()'s internal acquire()
    # (same file path, same resource key — see cli.py's `run_live_pr` command).
    live_challenger_store = SqliteResourceLeaseStore(lease_file)
    blocked = live_challenger_store.acquire(RESOURCE_NAME, "live-challenger-worker", ttl_seconds=3600)

    assert blocked is None

    runengine_lease.release()
    assert live_challenger_store.acquire(RESOURCE_NAME, "live-challenger-worker", ttl_seconds=3600) is not None
