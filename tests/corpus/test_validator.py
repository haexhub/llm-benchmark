from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from benchmark.cli import app
from benchmark.corpus import (
    CorpusValidationError,
    compute_suite_content_digest,
    materialize_review_input,
    record_curator_approval,
    validate_defect_label_scope,
    validate_protected_defect_label,
    validate_public_corpus,
)
from benchmark.corpus.oracle import ProtectedDefectLabel


def run_git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def create_valid_corpus(tmp_path: Path) -> Path:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    run_git("init", "--quiet", "--initial-branch=main", cwd=source_repo)

    (source_repo / "service.py").write_text("def value() -> int:\n    return 1\n")
    run_git("add", "service.py", cwd=source_repo)
    run_git(
        "-c",
        "user.name=Benchmark Test",
        "-c",
        "user.email=benchmark@example.test",
        "commit",
        "--quiet",
        "-m",
        "base",
        cwd=source_repo,
    )
    base_sha = run_git("rev-parse", "HEAD", cwd=source_repo)

    (source_repo / "service.py").write_text("def value() -> int:\n    return 0\n")
    run_git("add", "service.py", cwd=source_repo)
    run_git(
        "-c",
        "user.name=Benchmark Test",
        "-c",
        "user.email=benchmark@example.test",
        "commit",
        "--quiet",
        "-m",
        "buggy change",
        cwd=source_repo,
    )
    head_sha = run_git("rev-parse", "HEAD", cwd=source_repo)

    corpus_root = tmp_path / "review-corpus" / "review-v1"
    item_dir = corpus_root / "items" / "demo-item"
    item_dir.mkdir(parents=True)
    (item_dir / "policy.md").write_text("# Policy\n")
    run_git("bundle", "create", str(item_dir / "repo.bundle"), "main", cwd=source_repo)
    bundle_sha256 = hashlib.sha256((item_dir / "repo.bundle").read_bytes()).hexdigest()
    (item_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo-item",
                "partition": "development",
                "source": "synthetic",
                "approval_ref": "pending",
                "bundle_sha256": bundle_sha256,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "language": "python",
                "diff_size_bucket": "small",
                "difficulty": "easy",
            },
            sort_keys=False,
        )
    )
    (corpus_root / "suite.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "review-v1",
                "content_digest": compute_suite_content_digest(
                    [
                        (
                            "demo-item",
                            bundle_sha256,
                            hashlib.sha256((item_dir / "manifest.yaml").read_bytes()).hexdigest(),
                            hashlib.sha256((item_dir / "policy.md").read_bytes()).hexdigest(),
                        )
                    ]
                ),
            },
            sort_keys=False,
        )
    )
    return corpus_root


def test_validates_a_complete_public_item_with_verifiable_git_pair(tmp_path: Path) -> None:
    report = validate_public_corpus(create_valid_corpus(tmp_path))

    assert report.item_count == 1
    assert report.item_ids == ("demo-item",)


def test_materializes_a_runner_input_without_git_or_oracle_material(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)

    runner_input = materialize_review_input(corpus_root, "demo-item", tmp_path / "runner-input")

    assert runner_input.head_directory.joinpath("service.py").read_text().endswith("return 0\n")
    assert "-    return 1" in runner_input.diff_file.read_text()
    assert not runner_input.root.joinpath(".git").exists()
    assert not list(runner_input.root.rglob("ground-truth.yaml"))


def test_rejects_a_diff_that_deletes_a_protected_file_between_base_and_head(tmp_path: Path) -> None:
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    run_git("init", "--quiet", "--initial-branch=main", cwd=source_repo)

    (source_repo / "service.py").write_text("def value() -> int:\n    return 1\n")
    (source_repo / "ground-truth.yaml").write_text("defects: [{id: def-secret}]\n")
    run_git("add", "service.py", "ground-truth.yaml", cwd=source_repo)
    run_git(
        "-c",
        "user.name=Benchmark Test",
        "-c",
        "user.email=benchmark@example.test",
        "commit",
        "--quiet",
        "-m",
        "base",
        cwd=source_repo,
    )
    base_sha = run_git("rev-parse", "HEAD", cwd=source_repo)

    (source_repo / "service.py").write_text("def value() -> int:\n    return 0\n")
    run_git("mv", "ground-truth.yaml", "notes.yaml", cwd=source_repo)
    (source_repo / "notes.yaml").write_text("defects: [{id: def-secret}]\nextra: true\n")
    run_git("add", "service.py", cwd=source_repo)
    run_git(
        "-c",
        "user.name=Benchmark Test",
        "-c",
        "user.email=benchmark@example.test",
        "commit",
        "--quiet",
        "-m",
        "buggy change, rename oracle file",
        cwd=source_repo,
    )
    head_sha = run_git("rev-parse", "HEAD", cwd=source_repo)

    corpus_root = tmp_path / "review-corpus" / "review-v1"
    item_dir = corpus_root / "items" / "demo-item"
    item_dir.mkdir(parents=True)
    (item_dir / "policy.md").write_text("# Policy\n")
    run_git("bundle", "create", str(item_dir / "repo.bundle"), "main", cwd=source_repo)
    bundle_sha256 = hashlib.sha256((item_dir / "repo.bundle").read_bytes()).hexdigest()
    (item_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo-item",
                "partition": "development",
                "source": "synthetic",
                "approval_ref": "pending",
                "bundle_sha256": bundle_sha256,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "language": "python",
                "diff_size_bucket": "small",
                "difficulty": "easy",
            },
            sort_keys=False,
        )
    )
    (corpus_root / "suite.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "review-v1",
                "content_digest": compute_suite_content_digest(
                    [
                        (
                            "demo-item",
                            bundle_sha256,
                            hashlib.sha256((item_dir / "manifest.yaml").read_bytes()).hexdigest(),
                            hashlib.sha256((item_dir / "policy.md").read_bytes()).hexdigest(),
                        )
                    ]
                ),
            },
            sort_keys=False,
        )
    )

    with pytest.raises(CorpusValidationError, match="protected path"):
        materialize_review_input(corpus_root, "demo-item", tmp_path / "runner-input")


def test_rejects_a_suite_content_digest_that_does_not_match_its_items(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    suite_file = corpus_root / "suite.yaml"
    suite = yaml.safe_load(suite_file.read_text())
    suite["content_digest"] = "0" * 64
    suite_file.write_text(yaml.safe_dump(suite, sort_keys=False))

    with pytest.raises(CorpusValidationError, match="content_digest"):
        validate_public_corpus(corpus_root)


def test_suite_digest_covers_manifest_and_policy_bytes() -> None:
    records = [("demo-item", "b" * 64, "m" * 64, "p" * 64)]

    assert compute_suite_content_digest(records) != compute_suite_content_digest(
        [("demo-item", "b" * 64, "n" * 64, "p" * 64)]
    )
    assert compute_suite_content_digest(records) != compute_suite_content_digest(
        [("demo-item", "b" * 64, "m" * 64, "q" * 64)]
    )


def test_rejects_a_suite_id_that_does_not_match_its_directory_name(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    suite_file = corpus_root / "suite.yaml"
    suite = yaml.safe_load(suite_file.read_text())
    suite["id"] = "some-other-suite"
    suite_file.write_text(yaml.safe_dump(suite, sort_keys=False))

    with pytest.raises(CorpusValidationError, match="Suite manifest id"):
        validate_public_corpus(corpus_root)


def test_rejects_oracle_material_in_the_public_corpus(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    (corpus_root / "items" / "demo-item" / "ground-truth.yaml").write_text("defects: []\n")

    with pytest.raises(CorpusValidationError, match="oracle material"):
        validate_public_corpus(corpus_root)


def test_rejects_a_manifest_sha_missing_from_its_bundle(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    manifest_file = corpus_root / "items" / "demo-item" / "manifest.yaml"
    manifest = yaml.safe_load(manifest_file.read_text())
    manifest["head_sha"] = "0" * 40
    manifest_file.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(CorpusValidationError, match="demo-item: head_sha"):
        validate_public_corpus(corpus_root)


def test_rejects_a_bundle_with_a_digest_mismatch(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    bundle = corpus_root / "items" / "demo-item" / "repo.bundle"
    bundle.write_bytes(bundle.read_bytes() + b"tampered")

    with pytest.raises(CorpusValidationError, match="bundle_sha256"):
        validate_public_corpus(corpus_root)


def test_rejects_a_manifest_value_outside_the_published_contract(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    manifest_file = corpus_root / "items" / "demo-item" / "manifest.yaml"
    manifest = yaml.safe_load(manifest_file.read_text())
    manifest["partition"] = "production"
    manifest_file.write_text(yaml.safe_dump(manifest, sort_keys=False))

    with pytest.raises(CorpusValidationError, match="partition"):
        validate_public_corpus(corpus_root)


def test_validates_an_approved_protected_defect_label(tmp_path: Path) -> None:
    label_file = tmp_path / "ground-truth.yaml"
    label_file.write_text(
        yaml.safe_dump(
            {
                "id": "def-page-size-zero",
                "category": "correctness",
                "severity": "minor",
                "affected_scope": [{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
                "impact": "A zero page size violates the public API contract.",
                "reproducer_id": "rejects-zero-page-size",
                "approval": {
                    "reviewer_count": 2,
                    "state": "approved",
                    "curator_id": "operator",
                    "reviewed_at": "2026-09-22T00:00:00+00:00",
                    "evidence_digest": "a" * 64,
                },
            },
            sort_keys=False,
        )
    )

    label = validate_protected_defect_label(label_file)

    assert label.id == "def-page-size-zero"


def test_rejects_an_approved_label_without_audit_evidence(tmp_path: Path) -> None:
    label_file = tmp_path / "ground-truth.yaml"
    label_file.write_text(
        yaml.safe_dump(
            {
                "id": "def-page-size-zero",
                "category": "correctness",
                "severity": "minor",
                "affected_scope": [{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
                "impact": "A zero page size violates the public API contract.",
                "reproducer_id": "rejects-zero-page-size",
                "approval": {"reviewer_count": 0, "state": "approved"},
            },
            sort_keys=False,
        )
    )

    with pytest.raises(CorpusValidationError, match="approved"):
        validate_protected_defect_label(label_file)


def test_validates_a_single_curator_gold_label_with_auditable_evidence(tmp_path: Path) -> None:
    label_file = tmp_path / "ground-truth.yaml"
    label_file.write_text(
        yaml.safe_dump(
            {
                "id": "def-page-size-zero",
                "category": "correctness",
                "severity": "minor",
                "affected_scope": [{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
                "impact": "A zero page size violates the public API contract.",
                "reproducer_id": "rejects-zero-page-size",
                "approval": {
                    "reviewer_count": 1,
                    "state": "self_reviewed",
                    "curator_id": "operator",
                    "reviewed_at": datetime(2026, 9, 22, tzinfo=UTC).isoformat(),
                    "evidence_digest": "a" * 64,
                },
            },
            sort_keys=False,
        )
    )

    label = validate_protected_defect_label(label_file)

    assert label.approval.state == "self_reviewed"


def _demo_label(**overrides: object) -> ProtectedDefectLabel:
    fields = {
        "id": "def-page-size-zero",
        "category": "correctness",
        "severity": "minor",
        "affected_scope": [{"file": "service.py", "line_start": 1, "line_end": 2}],
        "impact": "A zero page size violates the public API contract.",
        "reproducer_id": "rejects-zero-page-size",
        "approval": {"reviewer_count": 0, "state": "pending"},
        **overrides,
    }
    return ProtectedDefectLabel.model_validate(fields)


def test_rejects_an_affected_scope_with_line_start_after_line_end() -> None:
    with pytest.raises(ValueError, match="line_start must not be greater than line_end"):
        _demo_label(affected_scope=[{"file": "service.py", "line_start": 5, "line_end": 1}])


def test_validates_a_defect_label_scope_within_the_head_revision(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    item_dir = corpus_root / "items" / "demo-item"
    manifest = yaml.safe_load((item_dir / "manifest.yaml").read_text())

    validate_defect_label_scope(
        item_dir / "repo.bundle", manifest["head_sha"], _demo_label(), "demo-item"
    )


def test_rejects_a_defect_label_scope_file_absent_from_head_revision(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    item_dir = corpus_root / "items" / "demo-item"
    manifest = yaml.safe_load((item_dir / "manifest.yaml").read_text())
    label = _demo_label(affected_scope=[{"file": "missing.py", "line_start": 1, "line_end": 1}])

    with pytest.raises(CorpusValidationError, match="absent from head_sha"):
        validate_defect_label_scope(item_dir / "repo.bundle", manifest["head_sha"], label, "demo-item")


def test_rejects_a_defect_label_scope_line_end_beyond_file_length(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    item_dir = corpus_root / "items" / "demo-item"
    manifest = yaml.safe_load((item_dir / "manifest.yaml").read_text())
    label = _demo_label(affected_scope=[{"file": "service.py", "line_start": 1, "line_end": 99}])

    with pytest.raises(CorpusValidationError, match="exceeds service.py"):
        validate_defect_label_scope(item_dir / "repo.bundle", manifest["head_sha"], label, "demo-item")


def test_rejects_a_defect_label_scope_line_start_beyond_file_length(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    item_dir = corpus_root / "items" / "demo-item"
    manifest = yaml.safe_load((item_dir / "manifest.yaml").read_text())
    label = _demo_label(affected_scope=[{"file": "service.py", "line_start": 99}])

    with pytest.raises(CorpusValidationError, match="line_start 99 exceeds service.py"):
        validate_defect_label_scope(item_dir / "repo.bundle", manifest["head_sha"], label, "demo-item")


def test_records_an_auditable_curator_approval(tmp_path: Path) -> None:
    label_file = tmp_path / "ground-truth.yaml"
    label_file.write_text(
        yaml.safe_dump(
            {
                "id": "def-page-size-zero",
                "category": "correctness",
                "severity": "minor",
                "affected_scope": [{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
                "impact": "A zero page size violates the public API contract.",
                "reproducer_id": "rejects-zero-page-size",
                "approval": {"reviewer_count": 0, "state": "pending"},
            },
            sort_keys=False,
        )
    )

    label = record_curator_approval(label_file, curator_id="haex", evidence_digest="a" * 64)

    assert label.approval.state == "self_reviewed"
    assert label.approval.curator_id == "haex"
    assert label.approval.decision_ready is True
    reloaded = validate_protected_defect_label(label_file)
    assert reloaded.approval.evidence_digest == "a" * 64


def test_cli_validates_a_public_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["corpus", "validate", str(create_valid_corpus(tmp_path))])

    assert result.exit_code == 0, result.output
    assert "Validated 1 public corpus item" in result.output
