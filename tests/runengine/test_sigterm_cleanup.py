"""Bug fix: a real SIGTERM mid-attempt must still release the resource lease and
mark the attempt terminal, not strand it at `running` for the rest of the lease
TTL. Mirrors test_lease_recovery.py's deterministic-cancellation style rather
than relying on real sleeps/timing races.
"""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

import yaml

from benchmark.corpus import compute_suite_content_digest
from benchmark.live import SqliteResourceLeaseStore
from benchmark.runengine.attempts import RESOURCE_NAME, ToolExecutionOutcome, run_attempt


def _run_git(*args: str, cwd: Path) -> str:
    """Run a Git command in the temporary fixture repository."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _create_valid_corpus(tmp_path: Path) -> Path:
    """Build a valid public corpus for the SIGTERM cleanup test."""
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
        self._conn.status_history.append(params)

    def fetchone(self) -> None:
        """Return the simulated single-row query result."""
        return None


class _FakeConnection:
    def __init__(self) -> None:
        """Initialize this test double with its simulated state."""
        self.status_history: list[tuple] = []

    def cursor(self) -> _FakeCursor:
        """Return a fake cursor bound to this connection."""
        return _FakeCursor(self)

    def commit(self) -> None:
        """Accept a commit without writing to a database."""
        pass


def test_sigterm_during_candidate_execution_releases_lease_and_marks_terminal(
    tmp_path: Path,
) -> None:
    """A real SIGTERM mid-attempt (e.g. `kill <pid>`, a supervisor stop) must not
    strand the attempt at `running` or leave the exclusive GPU lease held for the
    rest of its TTL — that would also block the production 004-live-pr-shadow-
    review feature, which shares the same lease/store."""
    corpus_root = _create_valid_corpus(tmp_path)
    lease_store = SqliteResourceLeaseStore(tmp_path / "run-engine.sqlite3")
    conn = _FakeConnection()
    cancelled = threading.Event()

    def executor(*, cancel_event: threading.Event, **kwargs) -> ToolExecutionOutcome:
        def _send_self_sigterm() -> None:
            time.sleep(0.05)
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=_send_self_sigterm, daemon=True).start()
        cancel_event.wait(timeout=5)
        cancelled.set()
        return ToolExecutionOutcome(
            ok=False, timed_out=False, returncode=-15, stdout="", stderr="terminated",
        )

    outcome = run_attempt(
        conn, store=object(), attempt_id=uuid4(), corpus_root=corpus_root, item_id="demo-item",
        candidate_slug="gito", model="m", config_hash="c" * 64,
        workspace_root=tmp_path / "workspaces", runs_dir=tmp_path,
        executor=executor, lease_store=lease_store,
    )

    assert outcome is None
    assert cancelled.is_set(), "executor's cancel_event was never set by the SIGTERM handler"

    terminal_updates = [
        p for p in conn.status_history
        if p and p[0] in {"failed", "succeeded", "invalid", "timed_out"}
    ]
    assert terminal_updates, "expected the attempt to reach a terminal status, not stay 'running'"
    assert not any(p[0] == "succeeded" for p in terminal_updates)
    assert any("signal" in (p[1] or "") for p in terminal_updates), (
        "expected an accurate terminal reason distinguishing a signal interrupt "
        "from a lost/expired lease"
    )

    reacquired = lease_store.acquire(RESOURCE_NAME, "someone-else", ttl_seconds=60)
    assert reacquired is not None, "lease was not released after SIGTERM cleanup"
