from __future__ import annotations

from uuid import uuid4

import pytest

from benchmark.corpus import (
    CorpusValidationError,
    FindingAssessment,
    ProtectedDefectLabel,
    UsefulnessAssessment,
    build_review_scorecard,
)


def test_scores_recall_separately_for_each_gold_category() -> None:
    correctness_defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py"}],
        impact="Zero violates the pagination contract.",
        reproducer_id="rejects-zero-page-size",
        approval={
            "reviewer_count": 2,
            "state": "approved",
            "curator_id": "operator",
            "reviewed_at": "2026-09-22T00:00:00+00:00",
            "evidence_digest": "a" * 64,
        },
    )
    security_defect = ProtectedDefectLabel(
        id="def-protocol-downgrade",
        category="security",
        severity="major",
        affected_scope=[{"file": "src/redirect.ts"}],
        impact="HTTP downgrades a trusted HTTPS origin.",
        reproducer_id="rejects-protocol-downgrade",
        approval={
            "reviewer_count": 2,
            "state": "approved",
            "curator_id": "operator",
            "reviewed_at": "2026-09-22T00:00:00+00:00",
            "evidence_digest": "a" * 64,
        },
    )
    assessments = [
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id="def-page-size-zero",
            outcome="matched",
            evidence="Confirmed against executable evidence.",
            evaluator_version="review-eval-v1",
        ),
        FindingAssessment(
            finding_id=None,
            gold_defect_id="def-protocol-downgrade",
            outcome="unmatched_gold",
            evidence="No confirmed matching finding was recorded.",
            evaluator_version="review-eval-v1",
        ),
    ]

    scorecard = build_review_scorecard(
        [correctness_defect, security_defect], assessments, reviewed_item_count=1
    )

    assert scorecard.recall == 0.5
    assert scorecard.severity_weighted_recall == pytest.approx(3 / 7)
    assert scorecard.categories["correctness"].recall == 1.0
    assert scorecard.categories["security"].recall == 0.0


def test_counts_duplicates_and_false_positives_as_attention_noise() -> None:
    defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py"}],
        impact="Zero violates the pagination contract.",
        reproducer_id="rejects-zero-page-size",
        approval={
            "reviewer_count": 2,
            "state": "approved",
            "curator_id": "operator",
            "reviewed_at": "2026-09-22T00:00:00+00:00",
            "evidence_digest": "a" * 64,
        },
    )
    assessments = [
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id=defect.id,
            outcome="matched",
            evidence="Confirmed evidence.",
            evaluator_version="review-eval-v1",
        ),
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id=defect.id,
            outcome="duplicate",
            evidence="Same evidence repeated.",
            evaluator_version="review-eval-v1",
        ),
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id=None,
            outcome="false_positive",
            evidence="No Gold evidence.",
            evaluator_version="review-eval-v1",
        ),
    ]

    scorecard = build_review_scorecard([defect], assessments, reviewed_item_count=2)

    assert scorecard.precision == pytest.approx(1 / 3)
    assert scorecard.duplicate_count == 1
    assert scorecard.false_positives_per_item == 0.5


def test_reports_useful_high_value_findings_per_attention_unit() -> None:
    defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py"}],
        impact="Zero violates the pagination contract.",
        reproducer_id="rejects-zero-page-size",
        approval={
            "reviewer_count": 2,
            "state": "approved",
            "curator_id": "operator",
            "reviewed_at": "2026-09-22T00:00:00+00:00",
            "evidence_digest": "a" * 64,
        },
    )
    assessments = [
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id=defect.id,
            outcome="matched",
            evidence="Confirmed evidence.",
            evaluator_version="review-eval-v1",
            usefulness=UsefulnessAssessment(
                correctness_source="gold_label",
                actionability=2,
                severity_calibration="calibrated",
                redundant=False,
                attention_cost=1,
                assessor_kind="human",
                assessor_version="rubric-v1",
            ),
        ),
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id=None,
            outcome="false_positive",
            evidence="No Gold evidence.",
            evaluator_version="review-eval-v1",
            usefulness=UsefulnessAssessment(
                correctness_source="human_adjudication",
                actionability=0,
                severity_calibration="not_applicable",
                redundant=False,
                attention_cost=3,
                assessor_kind="human",
                assessor_version="rubric-v1",
            ),
        ),
    ]

    scorecard = build_review_scorecard([defect], assessments, reviewed_item_count=1)

    assert scorecard.useful_high_value_count == 1
    assert scorecard.attention_cost_total == 4
    assert scorecard.useful_high_value_per_attention_unit == 0.25


def test_withholds_the_attention_ratio_when_a_finding_has_no_usefulness_assessment() -> None:
    defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py"}],
        impact="Zero violates the pagination contract.",
        reproducer_id="rejects-zero-page-size",
        approval={
            "reviewer_count": 2,
            "state": "approved",
            "curator_id": "operator",
            "reviewed_at": "2026-09-22T00:00:00+00:00",
            "evidence_digest": "a" * 64,
        },
    )
    assessments = [
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id=defect.id,
            outcome="matched",
            evidence="Confirmed evidence.",
            evaluator_version="review-eval-v1",
            usefulness=UsefulnessAssessment(
                correctness_source="gold_label",
                actionability=2,
                severity_calibration="calibrated",
                redundant=False,
                attention_cost=1,
                assessor_kind="human",
                assessor_version="rubric-v1",
            ),
        ),
        FindingAssessment(
            finding_id=uuid4(),
            gold_defect_id=None,
            outcome="false_positive",
            evidence="No Gold evidence.",
            evaluator_version="review-eval-v1",
            # Never rubric-assessed: must not be dropped from the denominator.
        ),
    ]

    scorecard = build_review_scorecard([defect], assessments, reviewed_item_count=1)

    assert scorecard.useful_high_value_count == 1
    assert scorecard.attention_cost_total == 1
    assert scorecard.useful_high_value_per_attention_unit is None


def test_refuses_to_score_a_pending_gold_label() -> None:
    pending_defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py"}],
        impact="Zero violates the pagination contract.",
        reproducer_id="rejects-zero-page-size",
        approval={"reviewer_count": 0, "state": "pending"},
    )

    with pytest.raises(CorpusValidationError, match="not decision-ready"):
        build_review_scorecard([pending_defect], [], reviewed_item_count=1)
