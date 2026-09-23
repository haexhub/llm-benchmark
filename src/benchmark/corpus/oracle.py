"""Validation helpers used only by protected post-run evaluator infrastructure."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .validator import CorpusValidationError, read_head_file_line_count


class AffectedScope(BaseModel):
    """The reviewed source location for one protected defect."""

    model_config = ConfigDict(extra="forbid", strict=True)

    file: Annotated[str, Field(min_length=1)]
    line_start: Annotated[int | None, Field(ge=1)] = None
    line_end: Annotated[int | None, Field(ge=1)] = None

    @model_validator(mode="after")
    def _ordered_line_range(self) -> AffectedScope:
        """Reject a scope whose starting line follows its ending line."""
        if (
            self.line_start is not None
            and self.line_end is not None
            and self.line_start > self.line_end
        ):
            raise ValueError("line_start must not be greater than line_end")
        return self


class LabelApproval(BaseModel):
    """Auditable curator ownership of a protected Gold label."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reviewer_count: Annotated[int, Field(ge=0)]
    state: Literal["pending", "self_reviewed", "approved", "adjudicated"]
    curator_id: Annotated[str | None, Field(min_length=1)] = None
    reviewed_at: Annotated[str | None, Field(min_length=1)] = None
    evidence_digest: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None

    @model_validator(mode="after")
    def _self_review_has_audit_trail(self) -> LabelApproval:
        audit_fields = (self.curator_id, self.reviewed_at, self.evidence_digest)
        if self.state == "pending" and self.reviewer_count != 0:
            raise ValueError("pending labels must have reviewer_count 0")
        if self.state == "self_reviewed" and (
            self.reviewer_count != 1 or any(field is None for field in audit_fields)
        ):
            raise ValueError(
                "self_reviewed labels require one curator plus reviewed_at and evidence_digest"
            )
        if self.state in {"approved", "adjudicated"} and (
            self.reviewer_count < 1 or any(field is None for field in audit_fields)
        ):
            raise ValueError(
                f"{self.state} labels require at least one reviewer plus reviewed_at and evidence_digest"
            )
        return self

    @property
    def decision_ready(self) -> bool:
        """Whether the label may participate in an official scorecard."""
        return self.state in {"self_reviewed", "approved", "adjudicated"}


class ProtectedDefectLabel(BaseModel):
    """The executable subset of the protected defect-label contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: Annotated[str, Field(pattern=r"^def-[a-z0-9-]{3,60}$")]
    category: Literal[
        "correctness", "security", "performance", "error_handling", "testing", "configuration"
    ]
    severity: Literal["critical", "major", "minor"]
    affected_scope: Annotated[list[AffectedScope], Field(min_length=1)]
    impact: Annotated[str, Field(min_length=1)]
    reproducer_id: Annotated[str, Field(min_length=1)]
    approval: LabelApproval


def validate_protected_defect_label(label_file: Path) -> ProtectedDefectLabel:
    """Validate one label in protected evaluator storage; never call from a runner."""
    if not label_file.is_file():
        raise CorpusValidationError(f"Missing protected defect label: {label_file}")
    try:
        document = yaml.safe_load(label_file.read_text())
    except yaml.YAMLError as error:
        raise CorpusValidationError(f"Invalid protected defect label YAML: {label_file}") from error
    if not isinstance(document, dict):
        raise CorpusValidationError(f"Protected defect label must be a YAML mapping: {label_file}")
    try:
        return ProtectedDefectLabel.model_validate(document)
    except ValidationError as error:
        raise CorpusValidationError(f"Protected defect label violates contract: {error}") from error


def record_curator_approval(
    label_file: Path,
    *,
    curator_id: str,
    evidence_digest: str,
    state: Literal["self_reviewed", "approved", "adjudicated"] = "self_reviewed",
) -> ProtectedDefectLabel:
    """Record an auditable human curator sign-off on a protected Gold label.

    This must only be called after the named curator has actually reviewed the
    label and its reproducer evidence; it is the accountable record of that
    review, not a substitute for it.
    """
    current = validate_protected_defect_label(label_file)
    if current.approval.state != "pending":
        raise CorpusValidationError(
            f"Cannot approve non-pending label: {label_file}"
        )
    document = yaml.safe_load(label_file.read_text())
    document["approval"] = {
        "reviewer_count": 1,
        "state": state,
        "curator_id": curator_id,
        "reviewed_at": datetime.now(UTC).isoformat(),
        "evidence_digest": evidence_digest,
    }
    try:
        updated = ProtectedDefectLabel.model_validate(document)
    except ValidationError as error:
        raise CorpusValidationError(f"Protected defect label approval is invalid: {error}") from error
    label_file.write_text(yaml.safe_dump(document, sort_keys=False))
    return updated


def validate_defect_label_scope(
    bundle: Path, head_sha: str, label: ProtectedDefectLabel, item_id: str
) -> None:
    """Verify every affected_scope location exists on the pinned Head revision."""
    for scope in label.affected_scope:
        line_count = read_head_file_line_count(bundle, head_sha, scope.file, item_id)
        if line_count is None:
            raise CorpusValidationError(
                f"{item_id}: {label.id} affected_scope file {scope.file} is absent from head_sha"
            )
        if scope.line_start is not None and scope.line_start > line_count:
            raise CorpusValidationError(
                f"{item_id}: {label.id} affected_scope line_start {scope.line_start} exceeds "
                f"{scope.file} ({line_count} lines) at head_sha"
            )
        if scope.line_end is not None and scope.line_end > line_count:
            raise CorpusValidationError(
                f"{item_id}: {label.id} affected_scope line_end {scope.line_end} exceeds "
                f"{scope.file} ({line_count} lines) at head_sha"
            )
