"""Coverage reporting across a public corpus and its protected Oracle package."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .oracle import validate_protected_defect_label
from .validator import CorpusValidationError

_EXPECTED_STRATA: dict[str, tuple[str, ...]] = {
    "language": ("python", "typescript"),
    "partition": ("development", "calibration", "holdout"),
    "source": ("public", "internal_deidentified", "synthetic"),
    "diff_size_bucket": ("small", "medium", "large"),
    "difficulty": ("easy", "medium", "hard"),
    "category": (
        "correctness",
        "security",
        "performance",
        "error_handling",
        "testing",
        "configuration",
    ),
    "severity": ("critical", "major", "minor"),
}


class _ManifestOnly(BaseModel):
    """A relaxed read of manifest.yaml for coverage counting only."""

    model_config = ConfigDict(extra="ignore")

    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")]
    partition: str
    source: str
    language: str
    diff_size_bucket: str
    difficulty: str


@dataclass(frozen=True)
class CoverageMatrix:
    """Item and defect counts across a suite, plus any zero-count strata."""

    item_count: int
    clean_count: int
    seeded_count: int
    pending_label_count: int
    decision_ready_label_count: int
    by_language: dict[str, int] = field(default_factory=dict)
    by_partition: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    by_diff_size: dict[str, int] = field(default_factory=dict)
    by_difficulty: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    missing_strata: tuple[str, ...] = ()

    @property
    def clean_ratio(self) -> float:
        """Return the fraction of items without an Oracle label, or zero for an empty suite."""
        return self.clean_count / self.item_count if self.item_count else 0.0


def build_coverage_matrix(corpus_root: Path, oracle_root: Path) -> CoverageMatrix:
    """Build a coverage matrix from a suite's public manifests and Oracle labels."""
    items_dir = corpus_root / "items"
    if not items_dir.is_dir():
        raise CorpusValidationError(f"Missing item directory: {items_dir}")
    if not oracle_root.is_dir():
        raise CorpusValidationError(f"Missing Oracle directory: {oracle_root}")

    counters: dict[str, Counter[str]] = {
        "language": Counter(),
        "partition": Counter(),
        "source": Counter(),
        "diff_size_bucket": Counter(),
        "difficulty": Counter(),
        "category": Counter(),
        "severity": Counter(),
    }

    item_count = 0
    clean_count = 0
    pending_label_count = 0
    decision_ready_label_count = 0

    for item_dir in sorted(path for path in items_dir.iterdir() if path.is_dir()):
        manifest = _load_manifest_for_coverage(item_dir / "manifest.yaml")
        if manifest.id != item_dir.name:
            raise CorpusValidationError(
                f"{item_dir.name}: manifest id must match its directory name"
            )
        item_count += 1
        counters["language"][manifest.language] += 1
        counters["partition"][manifest.partition] += 1
        counters["source"][manifest.source] += 1
        counters["diff_size_bucket"][manifest.diff_size_bucket] += 1
        counters["difficulty"][manifest.difficulty] += 1

        label_file = oracle_root / item_dir.name / "ground-truth.yaml"
        if not label_file.is_file():
            clean_count += 1
            continue
        label = validate_protected_defect_label(label_file)
        counters["category"][label.category] += 1
        counters["severity"][label.severity] += 1
        if label.approval.decision_ready:
            decision_ready_label_count += 1
        else:
            pending_label_count += 1

    missing = tuple(
        f"{dimension}={value}"
        for dimension, values in _EXPECTED_STRATA.items()
        for value in values
        if counters[dimension][value] == 0
    )

    return CoverageMatrix(
        item_count=item_count,
        clean_count=clean_count,
        seeded_count=item_count - clean_count,
        pending_label_count=pending_label_count,
        decision_ready_label_count=decision_ready_label_count,
        by_language=dict(counters["language"]),
        by_partition=dict(counters["partition"]),
        by_source=dict(counters["source"]),
        by_diff_size=dict(counters["diff_size_bucket"]),
        by_difficulty=dict(counters["difficulty"]),
        by_category=dict(counters["category"]),
        by_severity=dict(counters["severity"]),
        missing_strata=missing,
    )


def _load_manifest_for_coverage(manifest_file: Path) -> _ManifestOnly:
    """Read the manifest fields needed for coverage or reject a missing file."""
    if not manifest_file.is_file():
        raise CorpusValidationError(f"Missing manifest: {manifest_file}")
    try:
        document = yaml.safe_load(manifest_file.read_text())
    except yaml.YAMLError as error:
        raise CorpusValidationError(f"Invalid manifest YAML: {manifest_file}") from error
    try:
        return _ManifestOnly.model_validate(document)
    except ValidationError as error:
        raise CorpusValidationError(f"Manifest violates contract: {manifest_file}") from error


__all__ = ["CoverageMatrix", "build_coverage_matrix"]
