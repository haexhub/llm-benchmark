"""FR-009: automatic classification of findings against a corpus item's Gold label(s)."""
from __future__ import annotations

from uuid import uuid4

from benchmark.corpus.oracle import AffectedScope, LabelApproval, ProtectedDefectLabel
from benchmark.models import Finding
from benchmark.runengine.evaluator import evaluate_attempt_findings


def _label(label_id: str, file: str, line_start: int, line_end: int) -> ProtectedDefectLabel:
    """Build a protected defect label for the evaluation fixture."""
    return ProtectedDefectLabel(
        id=label_id,
        category="correctness",
        severity="major",
        affected_scope=[AffectedScope(file=file, line_start=line_start, line_end=line_end)],
        impact="test impact",
        reproducer_id="repro",
        approval=LabelApproval(reviewer_count=0, state="pending"),
    )


def _finding(file: str, line_start: int, line_end: int, title: str = "issue") -> Finding:
    """Build a finding for the evaluation fixture."""
    return Finding(
        id=uuid4(), tool="gito", file=file, line_start=line_start, line_end=line_end,
        severity="major", category="bug", title=title, body="body",
    )


def test_finding_overlapping_the_label_is_matched() -> None:
    """Verify finding overlapping the label is matched."""
    label = _label("def-aaa", "service.py", 10, 12)
    finding = _finding("service.py", 10, 12)

    result = evaluate_attempt_findings([finding], [label])

    assert result.finding_evaluations[0].outcome == "matched"
    assert result.finding_evaluations[0].gold_label_id == "def-aaa"
    assert result.matched_gold_label_count == 1
    assert result.missed_gold_label_count == 0


def test_second_finding_on_the_same_label_is_a_duplicate() -> None:
    """Verify second finding on the same label is a duplicate."""
    label = _label("def-aaa", "service.py", 10, 12)
    first = _finding("service.py", 10, 12, title="first")
    second = _finding("service.py", 11, 11, title="second")

    result = evaluate_attempt_findings([first, second], [label])

    outcomes = {fe.finding_id: fe.outcome for fe in result.finding_evaluations}
    assert outcomes[first.id] == "matched"
    assert outcomes[second.id] == "duplicate"


def test_finding_outside_tolerance_on_a_seeded_item_is_unmatched_gold() -> None:
    """Verify finding outside tolerance on a seeded item is unmatched gold."""
    label = _label("def-aaa", "service.py", 10, 12)
    finding = _finding("service.py", 100, 101)

    result = evaluate_attempt_findings([finding], [label])

    assert result.finding_evaluations[0].outcome == "unmatched_gold"
    assert result.finding_evaluations[0].gold_label_id is None
    assert result.missed_gold_label_count == 1


def test_any_finding_on_a_clean_control_is_false_positive() -> None:
    """Verify any finding on a clean control is false positive."""
    finding = _finding("service.py", 1, 2)

    result = evaluate_attempt_findings([finding], [])

    assert result.finding_evaluations[0].outcome == "false_positive"
    assert result.oracle_label_count == 0


def test_no_findings_on_a_seeded_item_misses_the_label() -> None:
    """Verify no findings on a seeded item misses the label."""
    label = _label("def-aaa", "service.py", 10, 12)

    result = evaluate_attempt_findings([], [label])

    assert result.finding_evaluations == ()
    assert result.oracle_label_count == 1
    assert result.matched_gold_label_count == 0
    assert result.missed_gold_label_count == 1


def test_line_tolerance_matches_a_few_lines_outside_the_label() -> None:
    """Verify line tolerance matches a few lines outside the label."""
    label = _label("def-aaa", "service.py", 10, 10)
    finding = _finding("service.py", 12, 13)  # 2 lines past line_end, within tolerance=3

    result = evaluate_attempt_findings([finding], [label])

    assert result.finding_evaluations[0].outcome == "matched"


def test_different_file_never_matches() -> None:
    """Verify different file never matches."""
    label = _label("def-aaa", "service.py", 10, 12)
    finding = _finding("other.py", 10, 12)

    result = evaluate_attempt_findings([finding], [label])

    assert result.finding_evaluations[0].outcome == "unmatched_gold"
