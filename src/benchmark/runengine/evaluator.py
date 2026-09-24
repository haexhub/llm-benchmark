"""Automatic classification of an Attempt's findings against the corpus Oracle (FR-009).

Note on `unmatched_gold`: this module's `unmatched_gold` means "a finding not
covered by any Gold label" (the finding's perspective). This is the opposite
of `benchmark.corpus.assessment.FindingAssessment`'s `unmatched_gold` (a Gold
label no finding matched, `finding_id=None`) — that module serves feature
003's human-curator corpus-authoring workflow and is not reused here; this is
a separate, fully-automatic classifier for scoring an already-released corpus
(FR-009 requires no human in the loop). The two are unrelated persisted
entities (Postgres `evaluation` rows vs. JSON `FindingAssessment` files) and
never mix, but the shared vocabulary is worth flagging for anyone reading both.

`false_positive` is only ever assigned automatically for a clean-control item
(zero Gold labels — there is nothing there to find, so any finding is
definitely wrong). `insufficient_evidence` is never assigned by this
automatic classifier; it remains a valid outcome value reserved for a future
human-adjudication path, not produced by FR-009's engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from benchmark.corpus.oracle import AffectedScope, ProtectedDefectLabel
from benchmark.models import Finding

EVALUATOR_VERSION = "runengine-evaluator-1"
LINE_TOLERANCE = 3  # matches matching/structural.py's cross-tool overlap convention

Outcome = Literal["matched", "duplicate", "false_positive", "insufficient_evidence", "unmatched_gold"]


@dataclass(frozen=True)
class FindingEvaluation:
    finding_id: UUID
    gold_label_id: str | None
    outcome: Outcome


@dataclass(frozen=True)
class AttemptEvaluation:
    finding_evaluations: tuple[FindingEvaluation, ...]
    oracle_label_count: int
    matched_gold_label_count: int
    missed_gold_label_count: int


def _scope_matches(finding: Finding, scope: AffectedScope) -> bool:
    if finding.file != scope.file:
        return False
    if scope.line_start is None or scope.line_end is None:
        return True  # file-level scope: any finding in this file counts
    lo = max(finding.line_start - LINE_TOLERANCE, scope.line_start)
    hi = min(finding.line_end + LINE_TOLERANCE, scope.line_end)
    return hi >= lo


def evaluate_attempt_findings(
    findings: list[Finding], gold_labels: list[ProtectedDefectLabel]
) -> AttemptEvaluation:
    """Classify every finding automatically against the item's Gold labels."""
    matched_label_ids: set[str] = set()
    evaluations: list[FindingEvaluation] = []
    is_clean_control = len(gold_labels) == 0

    for finding in findings:
        overlapping = [
            label
            for label in gold_labels
            if any(_scope_matches(finding, scope) for scope in label.affected_scope)
        ]
        unclaimed = [label for label in overlapping if label.id not in matched_label_ids]
        if unclaimed:
            chosen = unclaimed[0]
            matched_label_ids.add(chosen.id)
            evaluations.append(FindingEvaluation(finding.id, chosen.id, "matched"))
        elif overlapping:
            evaluations.append(FindingEvaluation(finding.id, overlapping[0].id, "duplicate"))
        elif is_clean_control:
            evaluations.append(FindingEvaluation(finding.id, None, "false_positive"))
        else:
            evaluations.append(FindingEvaluation(finding.id, None, "unmatched_gold"))

    return AttemptEvaluation(
        finding_evaluations=tuple(evaluations),
        oracle_label_count=len(gold_labels),
        matched_gold_label_count=len(matched_label_ids),
        missed_gold_label_count=len(gold_labels) - len(matched_label_ids),
    )
