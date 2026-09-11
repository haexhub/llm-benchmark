from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from benchmark.matching.aggregator import (
    apply_manual_reviews,
    classify_findings,
)
from benchmark.models import Finding, JudgeVerdict, ManualReview, Match


def _f(tool, file="a.py", start=10, end=None):
    return Finding(
        id=uuid4(),
        tool=tool,
        file=file,
        line_start=start,
        line_end=end if end is not None else start,
        severity="major",
        category="bug",
        title="t",
        body="b",
    )


def _verdict(same=True, conf=0.9):
    return JudgeVerdict(
        same=same,
        confidence=conf,
        reason="test",
        judge_model="test-model",
        prompt_hash="a" * 64,
    )


def test_classify_agreed_and_unique_and_missed() -> None:
    cr1 = _f("coderabbit", start=10)
    cr2 = _f("coderabbit", start=50)  # not matched
    t1 = _f("gito", start=10)  # matched with cr1
    t2 = _f("gito", start=100)  # unique to gito
    match = Match(
        a_id=cr1.id, b_id=t1.id, structural_overlap_lines=1, verdict=_verdict(), classification="same"
    )
    result = classify_findings([cr1, cr2], [t1, t2], [match])
    assert result[cr1.id] == "agreed_with_cr"
    assert result[cr2.id] == "missed_from_cr"
    assert result[t1.id] == "agreed_with_cr"
    assert result[t2.id] == "unique_to_tool"


def test_classify_ignores_different_classification() -> None:
    cr = _f("coderabbit")
    t = _f("gito")
    match = Match(a_id=cr.id, b_id=t.id, structural_overlap_lines=1, verdict=_verdict(same=False), classification="different")
    result = classify_findings([cr], [t], [match])
    assert result[cr.id] == "missed_from_cr"
    assert result[t.id] == "unique_to_tool"


def test_apply_manual_reviews_overrides_same_to_different() -> None:
    m = Match(a_id=uuid4(), b_id=uuid4(), structural_overlap_lines=1, verdict=_verdict(), classification="same")
    review = ManualReview(
        match_id=m.id, decision="different", reviewer="me", ts=datetime.now(UTC)
    )
    updated = apply_manual_reviews([m], [review])
    assert updated[0].classification == "different"


def test_apply_manual_reviews_unclear_maps_to_uncertain() -> None:
    m = Match(a_id=uuid4(), b_id=uuid4(), structural_overlap_lines=1, verdict=_verdict(), classification="same")
    review = ManualReview(
        match_id=m.id, decision="unclear", reviewer="me", ts=datetime.now(UTC)
    )
    updated = apply_manual_reviews([m], [review])
    assert updated[0].classification == "uncertain"


def test_apply_manual_reviews_ignores_unrelated_reviews() -> None:
    m = Match(a_id=uuid4(), b_id=uuid4(), structural_overlap_lines=1, verdict=_verdict(), classification="different")
    # Review points at some unknown match_id — no crash, no change
    unknown_review = ManualReview(
        match_id=uuid4(), decision="same", reviewer="me", ts=datetime.now(UTC)
    )
    updated = apply_manual_reviews([m], [unknown_review])
    assert updated[0].classification == "different"
