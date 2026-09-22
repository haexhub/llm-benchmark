"""Turn explicit evaluator decisions into immutable review-Gold assessments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from benchmark.models import Finding

from .oracle import ProtectedDefectLabel
from .validator import CorpusValidationError


class AssessmentDecision(BaseModel):
    """An evaluator's explicit conclusion about one tool finding."""

    model_config = ConfigDict(frozen=True)

    finding_id: UUID
    gold_defect_id: str | None
    outcome: Literal["matched", "false_positive", "insufficient_evidence"]
    evidence: str = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_gold_reference(self) -> AssessmentDecision:
        if self.outcome == "false_positive" and self.gold_defect_id is not None:
            raise ValueError("false_positive decisions must not reference a Gold defect")
        if self.outcome != "false_positive" and self.gold_defect_id is None:
            raise ValueError(f"{self.outcome} decisions must reference a Gold defect")
        return self


class UsefulnessAssessment(BaseModel):
    """Communication and attention-quality rubric, separate from correctness."""

    model_config = ConfigDict(frozen=True)

    correctness_source: Literal["gold_label", "executable_evidence", "human_adjudication"]
    actionability: int = Field(ge=0, le=2)
    severity_calibration: Literal["calibrated", "understated", "overstated", "not_applicable"]
    redundant: bool
    attention_cost: int = Field(ge=1, le=3)
    assessor_kind: Literal["human", "blind_judge"]
    assessor_version: str = Field(min_length=1)


class FindingAssessment(BaseModel):
    """A persisted, versioned result of comparing a finding with Ground Truth."""

    model_config = ConfigDict(frozen=True)

    finding_id: UUID | None
    gold_defect_id: str | None
    outcome: Literal[
        "matched", "duplicate", "false_positive", "insufficient_evidence", "unmatched_gold"
    ]
    evidence: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    usefulness: UsefulnessAssessment | None = None


def assess_findings(
    findings: list[Finding],
    gold_defects: list[ProtectedDefectLabel],
    decisions: list[AssessmentDecision],
    *,
    evaluator_version: str,
) -> list[FindingAssessment]:
    """Record explicit confirmed matches between tool findings and Gold defects."""
    finding_ids = {finding.id for finding in findings}
    gold_defect_ids = {defect.id for defect in gold_defects}
    if len(gold_defect_ids) != len(gold_defects):
        raise CorpusValidationError("Gold defect IDs must be unique")
    decision_finding_ids = [decision.finding_id for decision in decisions]
    if len(decision_finding_ids) != len(set(decision_finding_ids)) or set(
        decision_finding_ids
    ) != finding_ids:
        raise CorpusValidationError("Every finding must have exactly one decision")

    assessments: list[FindingAssessment] = []
    matched_gold_defect_ids: set[str] = set()
    for decision in decisions:
        if decision.finding_id not in finding_ids:
            raise CorpusValidationError(f"Decision references unknown finding: {decision.finding_id}")
        if decision.gold_defect_id is not None and decision.gold_defect_id not in gold_defect_ids:
            raise CorpusValidationError(f"Decision references unknown Gold defect: {decision.gold_defect_id}")
        if decision.outcome == "matched" and decision.gold_defect_id in matched_gold_defect_ids:
            outcome: Literal["matched", "duplicate", "false_positive", "insufficient_evidence"] = "duplicate"
        elif decision.outcome == "matched":
            outcome = "matched"
            matched_gold_defect_ids.add(decision.gold_defect_id)
        else:
            outcome = decision.outcome
        assessments.append(
            FindingAssessment(
                finding_id=decision.finding_id,
                gold_defect_id=decision.gold_defect_id,
                outcome=outcome,
                evidence=decision.evidence,
                evaluator_version=evaluator_version,
            )
        )
    for gold_defect in gold_defects:
        if gold_defect.id not in matched_gold_defect_ids:
            assessments.append(
                FindingAssessment(
                    finding_id=None,
                    gold_defect_id=gold_defect.id,
                    outcome="unmatched_gold",
                    evidence="No confirmed matching finding was recorded.",
                    evaluator_version=evaluator_version,
                )
            )
    return assessments


def save_assessments(destination: Path, assessments: list[FindingAssessment]) -> None:
    """Persist assessment evidence in a portable, versioned JSON document."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "assessments": [assessment.model_dump(mode="json") for assessment in assessments],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def load_assessments(source: Path) -> list[FindingAssessment]:
    """Load a version-1 assessment document for scoring or rendering."""
    document = json.loads(source.read_text())
    if document.get("schema_version") != "1":
        raise CorpusValidationError(f"Unsupported assessment schema: {document.get('schema_version')!r}")
    assessments = document.get("assessments")
    if not isinstance(assessments, list):
        raise CorpusValidationError("Assessment document must contain an assessments list")
    return [FindingAssessment.model_validate(assessment) for assessment in assessments]
