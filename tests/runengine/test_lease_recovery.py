"""US2: a lease lost mid-attempt (expired/reclaimed) must never be scored as a success.

Uses SqliteResourceLeaseStore's injectable clock (see tests/live/test_resource_lease.py)
to force expiry deterministically — no real sleep, no timing flakiness.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from uuid import uuid4

import yaml

from benchmark.corpus import compute_suite_content_digest
from benchmark.live import SqliteResourceLeaseStore
from benchmark.runengine.attempts import run_attempt


def _run_git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _create_valid_corpus(tmp_path: Path) -> Path:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    _run_git("init", "--quiet", "--initial-branch=main", cwd=source_repo)
    (source_repo / "service.py").write_text("def value() -> int:\n    return 1\n")
    _run_git("add", "service.py", cwd=source_repo)
    _run_git(
        "-c", "user.name=Benchmark Test", "-c", "user.email=benchmark@example.test",
        "commit", "--quiet", "-m", "base", cwd=source_repo,
    )
    base_sha = _run_git("rev-parse", "HEAD", cwd=source_repo)
    (source_repo / "service.py").write_text("def value() -> int:\n    return 0\n")
    _run_git("add", "service.py", cwd=source_repo)
    _run_git(
        "-c", "user.name=Benchmark Test", "-c", "user.email=benchmark@example.test",
        "commit", "--quiet", "-m", "buggy change", cwd=source_repo,
    )
    head_sha = _run_git("rev-parse", "HEAD", cwd=source_repo)

    corpus_root = tmp_path / "review-corpus" / "review-v1"
    item_dir = corpus_root / "items" / "demo-item"
    item_dir.mkdir(parents=True)
    (item_dir / "policy.md").write_text("# Policy\n")
    _run_git("bundle", "create", str(item_dir / "repo.bundle"), "main", cwd=source_repo)
    bundle_sha256 = hashlib.sha256((item_dir / "repo.bundle").read_bytes()).hexdigest()
    (item_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo-item", "partition": "development", "source": "synthetic",
                "approval_ref": "test-fixture", "bundle_sha256": bundle_sha256,
                "base_sha": base_sha, "head_sha": head_sha, "language": "python",
                "diff_size_bucket": "small", "difficulty": "easy",
            }
        )
    )
    content_digest = compute_suite_content_digest(
        [
            (
                "demo-item", bundle_sha256,
                hashlib.sha256((item_dir / "manifest.yaml").read_bytes()).hexdigest(),
                hashlib.sha256((item_dir / "policy.md").read_bytes()).hexdigest(),
            )
        ]
    )
    (corpus_root / "suite.yaml").write_text(
        yaml.safe_dump({"id": "review-v1", "content_digest": content_digest})
    )
    return corpus_root


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        self._conn = conn

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self._conn.status_history.append(params)
        if "status = 'running'" in sql:
            # Simulate enough wall-clock time passing during execution that
            # the lease expires before the post-execution renew() check.
            self._conn.clock[0] += 999999

    def fetchone(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, clock: list[float]) -> None:
        self.clock = clock
        self.status_history: list[tuple] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        pass


def _never_called(**kwargs):
    raise AssertionError("must not execute the candidate once the lease is confirmed lost")


def test_losing_the_lease_mid_attempt_marks_it_failed_without_running_the_candidate(
    tmp_path: Path,
) -> None:
    corpus_root = _create_valid_corpus(tmp_path)
    clock = [1000.0]
    lease_store = SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3", now=lambda: clock[0])
    conn = _FakeConnection(clock)

    outcome = run_attempt(
        conn, store=object(), attempt_id=uuid4(), corpus_root=corpus_root, item_id="demo-item",
        candidate_slug="gito", model="m", config_hash="c" * 64,
        workspace_root=tmp_path / "workspaces", runs_dir=tmp_path,
        executor=_never_called, lease_store=lease_store,
    )

    assert outcome is None
    terminal_updates = [p for p in conn.status_history if p and "failed" in p]
    assert terminal_updates, "expected the attempt to be marked failed, not silently dropped"
    assert not any(p and "succeeded" in p for p in conn.status_history)
