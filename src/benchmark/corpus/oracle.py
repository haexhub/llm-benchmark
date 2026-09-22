"""Validation helpers used only by protected post-run evaluator infrastructure."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .validator import CorpusValidationError


class AffectedScope(BaseModel):
    """The reviewed source location for one protected defect."""

    model_config = ConfigDict(extra="forbid", strict=True)

    file: Annotated[str, Field(min_length=1)]
    line_start: Annotated[int | None, Field(ge=1)] = None
    line_end: Annotated[int | None, Field(ge=1)] = None


class LabelApproval(BaseModel):
    """The independent review record required for decision-grade Gold labels."""

    model_config = ConfigDict(extra="forbid", strict=True)

    reviewer_count: Annotated[int, Field(ge=2)]
    state: Literal["approved", "adjudicated"]


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
