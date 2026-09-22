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
    materialize_review_input,
    validate_protected_defect_label,
    validate_public_corpus,
)


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
    (corpus_root / "suite.yaml").write_text("id: review-v1\n")
    (item_dir / "policy.md").write_text("# Policy\n")
    run_git("bundle", "create", str(item_dir / "repo.bundle"), "main", cwd=source_repo)
    (item_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "demo-item",
                "partition": "development",
                "kind": "seeded",
                "source": "synthetic",
                "approval_ref": "pending",
                "bundle_sha256": hashlib.sha256((item_dir / "repo.bundle").read_bytes()).hexdigest(),
                "base_sha": base_sha,
                "head_sha": head_sha,
                "language": "python",
                "diff_size_bucket": "small",
                "difficulty": "easy",
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
                "approval": {"reviewer_count": 2, "state": "approved"},
            },
            sort_keys=False,
        )
    )

    label = validate_protected_defect_label(label_file)

    assert label.id == "def-page-size-zero"


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


def test_cli_validates_a_public_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["corpus", "validate", str(create_valid_corpus(tmp_path))])

    assert result.exit_code == 0, result.output
    assert "Validated 1 public corpus item" in result.output
