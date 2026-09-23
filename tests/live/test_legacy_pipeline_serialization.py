from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

from benchmark import pipeline
from benchmark.live import SqliteResourceLeaseStore
from benchmark.models import RepoConfig


def test_legacy_pipeline_never_overlaps_local_challengers(tmp_path: Path) -> None:
    repo = RepoConfig(owner="alice", name="repo", pr_numbers=[1])
    run_directory = tmp_path / "runs" / repo.slug / "1"
    run_directory.mkdir(parents=True)
    active = {"count": 0, "maximum": 0}
    lock = threading.Lock()

    def tracker(*_args) -> None:
        with lock:
            active["count"] += 1
            active["maximum"] = max(active["maximum"], active["count"])
        time.sleep(0.02)
        with lock:
            active["count"] -= 1

    with patch("benchmark.pipeline._run_gito", side_effect=tracker), patch(
        "benchmark.pipeline._run_pragent", side_effect=tracker
    ):
        pipeline.do_run([repo], tmp_path / "runs", force=False, active_repo=None, active_pr=None)

    assert active["maximum"] == 1


def test_legacy_pipeline_skips_the_run_while_another_worker_holds_the_gpu_lease(tmp_path: Path) -> None:
    repo = RepoConfig(owner="alice", name="repo", pr_numbers=[1])
    run_directory = tmp_path / "runs" / repo.slug / "1"
    run_directory.mkdir(parents=True)
    lease_store = SqliteResourceLeaseStore(tmp_path / "runs" / "run-engine.sqlite3")
    lease = lease_store.acquire("local-94gb-gpu", "other-worker", ttl_seconds=60)
    assert lease is not None

    with patch("benchmark.pipeline._run_gito") as gito, patch("benchmark.pipeline._run_pragent") as pragent:
        pipeline.do_run([repo], tmp_path / "runs", force=False, active_repo=None, active_pr=None)

    gito.assert_not_called()
    pragent.assert_not_called()
    lease.release()
