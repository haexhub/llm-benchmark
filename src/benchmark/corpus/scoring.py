"""Category-oriented scorecards for Ground-Truth review assessments."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .assessment import FindingAssessment
from .oracle import ProtectedDefectLabel
from .validator import CorpusValidationError

_SEVERITY_WEIGHT = {"critical": 5, "major": 4, "minor": 3}


class ReviewCategoryScorecard(BaseModel):
    """Ground-Truth detection score for one defect category."""

    model_config = ConfigDict(frozen=True)

    gold_defect_count: int = Field(ge=0)
    matched_gold_count: int = Field(ge=0)
    recall: float = Field(ge=0.0, le=1.0)
    severity_weighted_recall: float = Field(ge=0.0, le=1.0)


class ReviewScorecard(BaseModel):
    """Non-ranked review effectiveness and noise metrics for one candidate."""

    model_config = ConfigDict(frozen=True)

    gold_defect_count: int = Field(ge=0)
    matched_gold_count: int = Field(ge=0)
    recall: float = Field(ge=0.0, le=1.0)
    severity_weighted_recall: float = Field(ge=0.0, le=1.0)
    categories: dict[str, ReviewCategoryScorecard]
    false_positive_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    insufficient_evidence_count: int = Field(ge=0)
    false_positives_per_item: float = Field(ge=0.0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    attention_cost_total: int = Field(ge=0)
    useful_high_value_count: int = Field(ge=0)
    useful_high_value_per_attention_unit: float | None = Field(default=None, ge=0.0, le=1.0)


def build_review_scorecard(
    gold_defects: list[ProtectedDefectLabel],
    assessments: list[FindingAssessment],
    *,
    reviewed_item_count: int,
) -> ReviewScorecard:
    """Build category scorecards without collapsing them into a rank."""
    if reviewed_item_count <= 0:
        raise CorpusValidationError("reviewed_item_count must be positive")
    pending_labels = [defect.id for defect in gold_defects if not defect.approval.decision_ready]
    if pending_labels:
        raise CorpusValidationError(f"Gold labels are not decision-ready: {pending_labels}")
    gold_by_id = {defect.id: defect for defect in gold_defects}
    if len(gold_by_id) != len(gold_defects):
        raise CorpusValidationError("Gold defect IDs must be unique")
    matched_ids = {
        assessment.gold_defect_id
        for assessment in assessments
        if assessment.outcome == "matched" and assessment.gold_defect_id is not None
    }
    unknown_ids = matched_ids - gold_by_id.keys()
    if unknown_ids:
        raise CorpusValidationError(f"Assessment references unknown Gold defects: {sorted(unknown_ids)}")

    categories = {
        category: _category_scorecard(
            [defect for defect in gold_defects if defect.category == category], matched_ids
        )
        for category in sorted({defect.category for defect in gold_defects})
    }
    overall = _category_scorecard(gold_defects, matched_ids)
    false_positive_count = sum(assessment.outcome == "false_positive" for assessment in assessments)
    duplicate_count = sum(assessment.outcome == "duplicate" for assessment in assessments)
    insufficient_evidence_count = sum(
        assessment.outcome == "insufficient_evidence" for assessment in assessments
    )
    attention_count = overall.matched_gold_count + duplicate_count + false_positive_count
    precision = overall.matched_gold_count / attention_count if attention_count else None
    finding_assessments = [assessment for assessment in assessments if assessment.finding_id is not None]
    attention_cost_total = sum(
        assessment.usefulness.attention_cost
        for assessment in finding_assessments
        if assessment.usefulness is not None
    )
    attention_cost_complete = bool(finding_assessments) and all(
        assessment.usefulness is not None for assessment in finding_assessments
    )
    useful_high_value_count = sum(
        assessment.outcome == "matched"
        and assessment.usefulness is not None
        and assessment.usefulness.actionability == 2
        and assessment.usefulness.severity_calibration == "calibrated"
        and not assessment.usefulness.redundant
        for assessment in assessments
    )

    return ReviewScorecard(
        gold_defect_count=overall.gold_defect_count,
        matched_gold_count=overall.matched_gold_count,
        recall=overall.recall,
        severity_weighted_recall=overall.severity_weighted_recall,
        categories=categories,
        false_positive_count=false_positive_count,
        duplicate_count=duplicate_count,
        insufficient_evidence_count=insufficient_evidence_count,
        false_positives_per_item=false_positive_count / reviewed_item_count,
        precision=precision,
        attention_cost_total=attention_cost_total,
        useful_high_value_count=useful_high_value_count,
        useful_high_value_per_attention_unit=(
            useful_high_value_count / attention_cost_total
            if attention_cost_complete and attention_cost_total
            else None
        ),
    )


def _category_scorecard(
    gold_defects: list[ProtectedDefectLabel], matched_ids: set[str]) -> ReviewCategoryScorecard:
    matched = [defect for defect in gold_defects if defect.id in matched_ids]
    total_weight = sum(_SEVERITY_WEIGHT[defect.severity] for defect in gold_defects)
    matched_weight = sum(_SEVERITY_WEIGHT[defect.severity] for defect in matched)
    return ReviewCategoryScorecard(
        gold_defect_count=len(gold_defects),
        matched_gold_count=len(matched),
        recall=len(matched) / len(gold_defects) if gold_defects else 0.0,
        severity_weighted_recall=matched_weight / total_weight if total_weight else 0.0,
    )
