"""db-marked: end-to-end plan run against a small fixture suite with a known
Gold label, verifying the score report matches hand-computed recall/precision/F1."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from benchmark.corpus import compute_suite_content_digest
from benchmark.matching.judge import NovelFindingVerdict
from benchmark.models import Finding
from benchmark.runengine.artifacts import ArtifactStore
from benchmark.runengine.attempts import ToolExecutionOutcome, create_attempts, run_attempt
from benchmark.runengine.candidate import register_candidate
from benchmark.runengine.db import connect, run_migrations
from benchmark.runengine.plan import PlanRequest, create_plan
from benchmark.runengine.scoring import compute_scores


def _run_git(*args: str, cwd: Path) -> str:
    """Run a Git command in the temporary fixture repository."""
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _create_seeded_corpus(tmp_path: Path) -> tuple[Path, Path]:
    """One item with exactly one known Gold defect at service.py:5-6."""
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    _run_git("init", "--quiet", "--initial-branch=main", cwd=source_repo)
    (source_repo / "service.py").write_text("\n".join(f"line {n}" for n in range(1, 10)) + "\n")
    _run_git("add", "service.py", cwd=source_repo)
    _run_git(
        "-c", "user.name=Benchmark Test", "-c", "user.email=benchmark@example.test",
        "commit", "--quiet", "-m", "base", cwd=source_repo,
    )
    base_sha = _run_git("rev-parse", "HEAD", cwd=source_repo)
    (source_repo / "service.py").write_text(
        "\n".join(f"line {n}" for n in range(1, 5)) + "\nbuggy line\n"
        + "\n".join(f"line {n}" for n in range(7, 10)) + "\n"
    )
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

    oracle_root = tmp_path / "corpus-oracle" / "review-v1"
    (oracle_root / "demo-item").mkdir(parents=True)
    (oracle_root / "demo-item" / "ground-truth.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "def-known-bug",
                "category": "correctness",
                "severity": "major",
                "affected_scope": [{"file": "service.py", "line_start": 5, "line_end": 5}],
                "impact": "test impact",
                "reproducer_id": "repro",
                "approval": {"reviewer_count": 1, "state": "approved", "curator_id": "haex",
                             "reviewed_at": "2026-01-01T00:00:00Z", "evidence_digest": "a" * 64},
            }
        )
    )
    return corpus_root, oracle_root


def _make_executor(findings: tuple[Finding, ...]):
    """Build an executor that returns controlled candidate findings."""
    def _executor(**kwargs) -> ToolExecutionOutcome:
        """Return deterministic candidate output for this test."""
        return ToolExecutionOutcome(
            ok=True, timed_out=False, returncode=0, stdout="", stderr="",
            raw_output=b"{}", findings=findings,
        )

    return _executor


class _AlwaysNotDefectJudge:
    def evaluate_novel_finding(self, finding: Finding, *, item_context: str) -> NovelFindingVerdict:
        """Return a controlled novel-finding verdict for the test."""
        return NovelFindingVerdict(
            verdict="not_defect", reasoning="test stub", judge_model="test",
            prompt_hash="b" * 64,
        )


@pytest.mark.db
def test_score_matches_hand_computed_recall_precision_f1(tmp_path: Path) -> None:
    """Verify score matches hand computed recall precision f1."""
    corpus_root, oracle_root = _create_seeded_corpus(tmp_path)
    conn = connect()
    run_migrations(conn)
    store = ArtifactStore()
    store.ensure_bucket()

    candidate = register_candidate(
        conn, slug="gito", tool_version=f"test-{uuid4()}", package_digest="d" * 64,
        model_endpoint_config_hash="e" * 64,
    )
    suite_manifest = yaml.safe_load((corpus_root / "suite.yaml").read_text())
    plan = create_plan(
        conn,
        PlanRequest(
            suite_version_digest=suite_manifest["content_digest"],
            candidate_version_ids=(candidate.id,), repetitions=1, retry_cap=0,
            score_policy_version="review-v1-policy-1", created_by=f"test-{uuid4()}",
        ),
    )
    attempts = create_attempts(
        conn, store, plan, ["demo-item"], model="test-model",
        config_hash_by_candidate={candidate.id: candidate.model_endpoint_config_hash},
    )
    assert len(attempts) == 1

    # One correct match (line 5, the real bug) + one extra finding elsewhere
    # (unmatched_gold -> judge says not_defect, must never affect the score).
    findings = (
        Finding(id=uuid4(), tool="gito", file="service.py", line_start=5, line_end=5,
                severity="major", category="bug", title="real bug", body="found it"),
        Finding(id=uuid4(), tool="gito", file="service.py", line_start=1, line_end=1,
                severity="minor", category="style", title="unrelated nit", body="not the bug"),
    )
    outcome = run_attempt(
        conn, store, attempt_id=attempts[0].id, corpus_root=corpus_root, item_id="demo-item",
        candidate_slug="gito", model="test-model",
        config_hash=candidate.model_endpoint_config_hash,
        workspace_root=tmp_path / "workspaces", runs_dir=tmp_path / "runs",
        executor=_make_executor(findings), oracle_root=oracle_root,
        novel_finding_judge=_AlwaysNotDefectJudge(),
    )
    assert outcome is not None and outcome.ok is True

    metrics = compute_scores(conn, plan_id=plan.id, candidate_version_id=candidate.id)

    # 1 Gold label, matched once -> recall 1.0. 2 findings, 1 matched -> precision 0.5.
    assert metrics["recall"].value == 1.0
    assert metrics["precision"].value == 0.5
    expected_f1 = 2 * 1.0 * 0.5 / (1.0 + 0.5)
    assert metrics["f1"].value == pytest.approx(expected_f1)
    assert metrics["duplicate_rate"].value == 0.0

    with conn.cursor() as cur:
        cur.execute(
            "SELECT outcome FROM evaluation WHERE attempt_id = %s ORDER BY outcome", (attempts[0].id,)
        )
        outcomes = [row[0] for row in cur.fetchall()]
    assert sorted(outcomes) == ["matched", "unmatched_gold"]
    conn.close()


@pytest.mark.db
def test_novel_finding_judge_verdict_never_changes_the_score(tmp_path: Path) -> None:
    """Verify novel finding judge verdict never changes the score."""
    corpus_root, oracle_root = _create_seeded_corpus(tmp_path)
    conn = connect()
    run_migrations(conn)
    store = ArtifactStore()
    store.ensure_bucket()

    candidate = register_candidate(
        conn, slug="gito", tool_version=f"test-{uuid4()}", package_digest="d" * 64,
        model_endpoint_config_hash="e" * 64,
    )
    suite_manifest = yaml.safe_load((corpus_root / "suite.yaml").read_text())
    plan = create_plan(
        conn,
        PlanRequest(
            suite_version_digest=suite_manifest["content_digest"],
            candidate_version_ids=(candidate.id,), repetitions=1, retry_cap=0,
            score_policy_version="review-v1-policy-1", created_by=f"test-{uuid4()}",
        ),
    )
    attempts = create_attempts(
        conn, store, plan, ["demo-item"], model="test-model",
        config_hash_by_candidate={candidate.id: candidate.model_endpoint_config_hash},
    )

    novel_finding = Finding(
        id=uuid4(), tool="gito", file="service.py", line_start=1, line_end=1,
        severity="minor", category="style", title="novel", body="beyond gold",
    )
    run_attempt(
        conn, store, attempt_id=attempts[0].id, corpus_root=corpus_root, item_id="demo-item",
        candidate_slug="gito", model="test-model",
        config_hash=candidate.model_endpoint_config_hash,
        workspace_root=tmp_path / "workspaces", runs_dir=tmp_path / "runs",
        executor=_make_executor((novel_finding,)), oracle_root=oracle_root,
        novel_finding_judge=_AlwaysNotDefectJudge(),
    )

    metrics_before = compute_scores(conn, plan_id=plan.id, candidate_version_id=candidate.id)
    # A stubbed judge already ran above; recompute is a no-op, only checking
    # the score is exactly what the Oracle-only classification produced.
    assert metrics_before["recall"].value == 0.0  # missed the one real Gold label
    assert metrics_before["precision"].value == 0.0  # the one finding was unmatched_gold

    with conn.cursor() as cur:
        cur.execute(
            "SELECT verdict FROM novel_finding_review nfr JOIN evaluation e ON e.id = nfr.evaluation_id "
            "WHERE e.attempt_id = %s",
            (attempts[0].id,),
        )
        (verdict,) = cur.fetchone()
    assert verdict == "not_defect"
    conn.close()
