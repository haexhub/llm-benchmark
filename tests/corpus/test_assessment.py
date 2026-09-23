from __future__ import annotations

from uuid import uuid4

import pytest

from benchmark.corpus import (
    AssessmentDecision,
    CorpusValidationError,
    FindingAssessment,
    ProtectedDefectLabel,
    UsefulnessAssessment,
    assess_findings,
    load_assessments,
    save_assessments,
)
from benchmark.models import Finding


def test_assesses_a_confirmed_finding_as_a_gold_match() -> None:
    finding = Finding(
        tool="gito",
        file="src/paging.py",
        line_start=3,
        line_end=4,
        severity="minor",
        category="bug",
        title="Zero page size is accepted",
        body="The validator accepts a zero page size.",
    )
    gold_defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
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

    assessments = assess_findings(
        [finding],
        [gold_defect],
        [
            AssessmentDecision(
                finding_id=finding.id,
                gold_defect_id=gold_defect.id,
                outcome="matched",
                evidence="Same invalid zero-page-size acceptance at src/paging.py:3.",
            )
        ],
        evaluator_version="review-eval-v1",
    )

    assert len(assessments) == 1
    assert assessments[0].finding_id == finding.id
    assert assessments[0].gold_defect_id == "def-page-size-zero"
    assert assessments[0].outcome == "matched"


def test_marks_a_second_confirmed_finding_for_the_same_gold_defect_as_duplicate() -> None:
    first_finding = Finding(
        tool="gito",
        file="src/paging.py",
        line_start=3,
        line_end=4,
        severity="minor",
        category="bug",
        title="Zero page size is accepted",
        body="The validator accepts a zero page size.",
    )
    second_finding = first_finding.model_copy(
        update={"id": uuid4(), "title": "Page size needs a positive lower bound"}
    )
    gold_defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
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

    assessments = assess_findings(
        [first_finding, second_finding],
        [gold_defect],
        [
            AssessmentDecision(
                finding_id=first_finding.id,
                gold_defect_id=gold_defect.id,
                outcome="matched",
                evidence="Same invalid zero-page-size acceptance.",
            ),
            AssessmentDecision(
                finding_id=second_finding.id,
                gold_defect_id=gold_defect.id,
                outcome="matched",
                evidence="Same invalid zero-page-size acceptance.",
            ),
        ],
        evaluator_version="review-eval-v1",
    )

    assert [assessment.outcome for assessment in assessments] == ["matched", "duplicate"]


def test_reports_false_positives_and_unmatched_gold_separately() -> None:
    finding = Finding(
        tool="pr-agent",
        file="src/paging.py",
        line_start=1,
        line_end=1,
        severity="minor",
        category="style",
        title="Unrelated naming suggestion",
        body="Rename this function for consistency.",
    )
    gold_defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
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

    assessments = assess_findings(
        [finding],
        [gold_defect],
        [
            AssessmentDecision(
                finding_id=finding.id,
                gold_defect_id=None,
                outcome="false_positive",
                evidence="No Gold defect corresponds to this naming suggestion.",
            )
        ],
        evaluator_version="review-eval-v1",
    )

    assert [(assessment.finding_id, assessment.outcome) for assessment in assessments] == [
        (finding.id, "false_positive"),
        (None, "unmatched_gold"),
    ]


def test_keeps_insufficient_evidence_out_of_true_and_false_counts() -> None:
    finding = Finding(
        tool="coderabbit",
        file="src/paging.py",
        line_start=3,
        line_end=4,
        severity="minor",
        category="bug",
        title="Possibly invalid page size",
        body="The effect cannot be confirmed from this comment alone.",
    )
    gold_defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
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

    assessments = assess_findings(
        [finding],
        [gold_defect],
        [
            AssessmentDecision(
                finding_id=finding.id,
                gold_defect_id=gold_defect.id,
                outcome="insufficient_evidence",
                evidence="The finding does not establish whether zero is accepted.",
            )
        ],
        evaluator_version="review-eval-v1",
    )

    assert [assessment.outcome for assessment in assessments] == [
        "insufficient_evidence",
        "unmatched_gold",
    ]


def test_persists_versioned_assessments_without_losing_evidence(tmp_path) -> None:
    assessment = FindingAssessment(
        finding_id=None,
        gold_defect_id="def-page-size-zero",
        outcome="unmatched_gold",
        evidence="No confirmed matching finding was recorded.",
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
    )
    destination = tmp_path / "assessments.json"

    save_assessments(destination, [assessment])

    assert load_assessments(destination) == [assessment]


def test_rejects_an_assessment_batch_that_leaves_a_finding_undecided() -> None:
    finding = Finding(
        tool="gito",
        file="src/paging.py",
        line_start=3,
        line_end=4,
        severity="minor",
        category="bug",
        title="Zero page size is accepted",
        body="The validator accepts a zero page size.",
    )
    gold_defect = ProtectedDefectLabel(
        id="def-page-size-zero",
        category="correctness",
        severity="minor",
        affected_scope=[{"file": "src/paging.py", "line_start": 3, "line_end": 4}],
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

    with pytest.raises(CorpusValidationError, match="exactly one decision"):
        assess_findings([finding], [gold_defect], [], evaluator_version="review-eval-v1")
