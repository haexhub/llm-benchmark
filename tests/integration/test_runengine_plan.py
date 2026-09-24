"""db-marked: end-to-end plan create -> plan run against real Postgres/RustFS,
with a stubbed candidate executor (no real gito/pr-agent/LLM calls)."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from benchmark.corpus import compute_suite_content_digest
from benchmark.runengine.artifacts import ArtifactStore
from benchmark.runengine.attempts import ToolExecutionOutcome, create_attempts, run_attempt
from benchmark.runengine.candidate import register_candidate
from benchmark.runengine.db import connect, run_migrations
from benchmark.runengine.plan import PlanRequest, create_plan


def _run_git(*args: str, cwd: Path) -> str:
    """Run a Git command in the temporary fixture repository."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _create_single_item_corpus(tmp_path: Path) -> Path:
    """Build a one-item corpus for the integration scenario."""
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


def _stub_executor(**kwargs) -> ToolExecutionOutcome:
    """Return controlled candidate output for the integration scenario."""
    return ToolExecutionOutcome(
        ok=True, timed_out=False, returncode=0, stdout="", stderr="",
        raw_output=b'{"findings": []}', findings=(),
    )


@pytest.mark.db
def test_plan_create_then_run_produces_distinct_manifests_with_no_oracle_leakage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify plan create then run produces distinct manifests with no oracle leakage."""
    monkeypatch.setattr(
        "benchmark.runengine.candidate.run_capability_probe",
        lambda slug, tool_version: ("passed", {"stub": True}),
    )
    corpus_root = _create_single_item_corpus(tmp_path)
    conn = connect()
    run_migrations(conn)
    store = ArtifactStore()
    store.ensure_bucket()

    candidate = register_candidate(
        conn, slug="gito", tool_version=f"test-{uuid4()}", package_digest="d" * 64,
        model_endpoint_config_hash="e" * 64,
    )
    suite_manifest = yaml.safe_load((corpus_root / "suite.yaml").read_text())
    request = PlanRequest(
        suite_version_digest=suite_manifest["content_digest"],
        candidate_version_ids=(candidate.id,),
        repetitions=2,
        retry_cap=3,
        score_policy_version="review-v1-policy-1",
        created_by=f"test-actor-{uuid4()}",
    )
    plan = create_plan(conn, request)
    attempts = create_attempts(
        conn, store, plan, ["demo-item"], model="test-model",
        config_hash_by_candidate={candidate.id: candidate.model_endpoint_config_hash},
    )

    assert len(attempts) == 2
    assert len({a.id for a in attempts}) == 2

    workspace_root = tmp_path / "workspaces"
    for attempt in attempts:
        outcome = run_attempt(
            conn, store, attempt_id=attempt.id, corpus_root=corpus_root, item_id="demo-item",
            candidate_slug="gito", model="test-model",
            config_hash=candidate.model_endpoint_config_hash,
            workspace_root=workspace_root, runs_dir=tmp_path / "runs",
            executor=_stub_executor,
        )
        assert outcome is not None
        assert outcome.ok is True

    with conn.cursor() as cur:
        cur.execute("SELECT status FROM attempt WHERE plan_id = %s", (plan.id,))
        statuses = [row[0] for row in cur.fetchall()]
    assert statuses == ["succeeded", "succeeded"]

    all_workspace_names = {p.name for p in workspace_root.rglob("*")}
    assert "ground-truth.yaml" not in all_workspace_names
    assert "reproducers" not in all_workspace_names
    conn.close()
