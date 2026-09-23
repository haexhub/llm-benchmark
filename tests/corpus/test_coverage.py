from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from benchmark.cli import app
from benchmark.corpus import (
    CorpusValidationError,
    build_coverage_matrix,
    compute_suite_content_digest,
)


def _run_git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def create_valid_corpus(tmp_path: Path) -> Path:
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


def _write_label(oracle_root: Path, item_id: str, **overrides: object) -> None:
    fields = {
        "id": f"def-{item_id}",
        "category": "correctness",
        "severity": "minor",
        "affected_scope": [{"file": "service.py", "line_start": 1, "line_end": 2}],
        "impact": "A defect.",
        "reproducer_id": "reproduces-it",
        "approval": {"reviewer_count": 0, "state": "pending"},
        **overrides,
    }
    item_dir = oracle_root / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "ground-truth.yaml").write_text(yaml.safe_dump(fields, sort_keys=False))


def test_reports_a_clean_control_with_no_ground_truth_file(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()

    matrix = build_coverage_matrix(corpus_root, oracle_root)

    assert matrix.item_count == 1
    assert matrix.clean_count == 1
    assert matrix.seeded_count == 0
    assert matrix.by_language == {"python": 1}


def test_counts_a_seeded_item_and_its_label_dimensions(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    oracle_root = tmp_path / "oracle"
    _write_label(oracle_root, "demo-item", category="security", severity="critical")

    matrix = build_coverage_matrix(corpus_root, oracle_root)

    assert matrix.clean_count == 0
    assert matrix.seeded_count == 1
    assert matrix.by_category == {"security": 1}
    assert matrix.by_severity == {"critical": 1}
    assert matrix.pending_label_count == 1
    assert matrix.decision_ready_label_count == 0


def test_lists_zero_count_strata_as_missing(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()

    matrix = build_coverage_matrix(corpus_root, oracle_root)

    assert "language=typescript" in matrix.missing_strata
    assert "category=performance" in matrix.missing_strata
    assert "language=python" not in matrix.missing_strata


def test_rejects_a_missing_oracle_directory(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)

    with pytest.raises(CorpusValidationError, match="Missing Oracle directory"):
        build_coverage_matrix(corpus_root, tmp_path / "missing-oracle")


def test_binds_oracle_lookup_to_item_directory(tmp_path: Path) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    item_manifest = corpus_root / "items" / "demo-item" / "manifest.yaml"
    document = yaml.safe_load(item_manifest.read_text())
    document["id"] = "other-item"
    item_manifest.write_text(yaml.safe_dump(document, sort_keys=False))
    oracle_root = tmp_path / "oracle"
    _write_label(oracle_root, "other-item")

    with pytest.raises(CorpusValidationError, match="manifest id must match"):
        build_coverage_matrix(corpus_root, oracle_root)


@pytest.mark.parametrize("manifest_text", ["id: demo-item\n", "id: [invalid\n"])
def test_converts_invalid_manifest_to_corpus_validation_error(
    tmp_path: Path, manifest_text: str
) -> None:
    corpus_root = create_valid_corpus(tmp_path)
    manifest_file = corpus_root / "items" / "demo-item" / "manifest.yaml"
    manifest_file.write_text(manifest_text)
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()

    with pytest.raises(CorpusValidationError):
        build_coverage_matrix(corpus_root, oracle_root)


def test_cli_renders_a_coverage_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    corpus_root = create_valid_corpus(tmp_path)
    oracle_root = tmp_path / "oracle"
    oracle_root.mkdir()

    result = CliRunner().invoke(app, ["corpus", "coverage", str(corpus_root), str(oracle_root)])

    assert result.exit_code == 0, result.output
    assert "Items: 1" in result.output
