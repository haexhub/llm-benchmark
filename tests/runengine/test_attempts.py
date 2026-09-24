"""US1: attempt manifest contract + fresh-workspace Oracle isolation. US4: schema-drift handling."""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import yaml

from benchmark.corpus import compute_suite_content_digest
from benchmark.runengine.attempts import (
    ToolExecutionOutcome,
    _build_manifest,
    _finish_execution,
    item_uuid,
    materialize_workspace,
)
from benchmark.tools.base import RunResult


def _run_git(*args: str, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def create_valid_corpus(tmp_path: Path) -> Path:
    """Minimal single-item public corpus, mirroring tests/corpus/test_validator.py's fixture."""
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

    manifest = {
        "id": "demo-item",
        "partition": "development",
        "source": "synthetic",
        "approval_ref": "test-fixture",
        "bundle_sha256": bundle_sha256,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "language": "python",
        "diff_size_bucket": "small",
        "difficulty": "easy",
    }
    (item_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest))

    content_digest = compute_suite_content_digest(
        [
            (
                "demo-item",
                bundle_sha256,
                hashlib.sha256((item_dir / "manifest.yaml").read_bytes()).hexdigest(),
                hashlib.sha256((item_dir / "policy.md").read_bytes()).hexdigest(),
            )
        ]
    )
    (corpus_root / "suite.yaml").write_text(
        yaml.safe_dump({"id": "review-v1", "content_digest": content_digest})
    )
    return corpus_root


def test_manifest_has_fixed_axis_and_no_warmup() -> None:
    manifest = _build_manifest(
        attempt_id=uuid4(), suite_version_digest="d" * 64, item_id="demo-item",
        candidate_version_id=uuid4(), model="qwen-3-30b", config_hash="c" * 64,
        score_policy_version="review-v1-policy-1", resource_profile="local-94gb-gpu",
        created_at=datetime.now(UTC),
    )
    assert manifest["is_warmup"] is False
    assert manifest["comparison_axis"] == "end_to_end_agent"
    assert manifest["suite_version_digest"] == f"sha256:{'d' * 64}"
    assert manifest["config_hash"] == f"sha256:{'c' * 64}"
    # attempt-manifest.schema.json requires item_id to be a uuid; corpus items are slugs.
    assert UUID(manifest["item_id"]) == item_uuid("demo-item")


def test_manifest_item_id_is_stable_for_the_same_slug() -> None:
    assert item_uuid("demo-item") == item_uuid("demo-item")
    assert item_uuid("demo-item") != item_uuid("other-item")


def test_materialized_workspace_has_no_oracle_material(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    workspace = tmp_path / "workspace"

    runner_input = materialize_workspace(corpus_root, "demo-item", workspace)

    all_names = {p.name for p in runner_input.root.rglob("*")}
    assert "ground-truth.yaml" not in all_names
    assert "reproducers" not in all_names
    assert "approvals.yaml" not in all_names
    assert not (runner_input.root / ".git").exists()
    assert runner_input.diff_file.exists()
    assert runner_input.head_directory.exists()


def test_schema_drift_is_detected_and_never_treated_as_zero_findings(tmp_path: Path) -> None:
    bad_output = tmp_path / "pr-agent.json"
    bad_output.write_text("not json at all")
    result = RunResult(returncode=0, stdout="", stderr="", timed_out=False)

    def _loader(path: Path) -> list:
        return json.loads(path.read_text())  # raises ValueError on bad JSON

    outcome = _finish_execution(result, bad_output, _loader)

    assert outcome.ok is False
    assert outcome.schema_drift is True
    assert isinstance(outcome, ToolExecutionOutcome)


def test_successful_output_is_not_flagged_as_drift(tmp_path: Path) -> None:
    good_output = tmp_path / "pr-agent.json"
    good_output.write_text("[]")
    result = RunResult(returncode=0, stdout="", stderr="", timed_out=False)

    outcome = _finish_execution(result, good_output, lambda p: [])

    assert outcome.ok is True
    assert outcome.schema_drift is False
    assert outcome.findings == ()
