"""Aggregate matches → per-Finding classification (agreed_with_cr / unique_to_tool / missed_from_cr).

Also apply ManualReview overrides.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Literal
from uuid import UUID

from benchmark.models import Finding, ManualReview, Match

log = logging.getLogger("benchmark.aggregator")

FindingClassification = Literal["agreed_with_cr", "unique_to_tool", "missed_from_cr"]
UNCERTAIN_CONFIDENCE_THRESHOLD = 0.6


def apply_manual_reviews(matches: list[Match], reviews: Iterable[ManualReview]) -> list[Match]:
    """Return a new list with Match.classification overridden per reviewer decision."""
    by_match_id = {r.match_id: r for r in reviews}
    updated: list[Match] = []
    for m in matches:
        review = by_match_id.get(m.id)
        if review is None:
            updated.append(m)
            continue
        # Manual "unclear" → keep uncertain; explicit "same"/"different" overrides.
        if review.decision == "unclear":
            updated.append(m.model_copy(update={"classification": "uncertain"}))
        else:
            updated.append(m.model_copy(update={"classification": review.decision}))
    return updated


def load_manual_reviews(path: Path) -> list[ManualReview]:
    if not path.exists():
        return []
    with path.open() as fh:
        payload = json.load(fh)
    return [ManualReview.model_validate(r) for r in payload.get("reviews", [])]


def classify_findings(
    cr_findings: list[Finding],
    tool_findings: list[Finding],
    matches: list[Match],
) -> dict[UUID, FindingClassification]:
    """Per tool-Finding: is there a same-classified Match linking it to a CR finding?

    Returns {finding_id: classification}. `finding_id` covers both CR- and tool-findings:
    - CR findings that share a `same` match get `agreed_with_cr` (the paired tool-finding
      is also `agreed_with_cr`).
    - Tool findings not in any `same` match with CR are `unique_to_tool`.
    - CR findings not in any `same` match with any tool are `missed_from_cr` (per that tool).
    Caller usually passes one tool at a time (call this once per tool per PR).
    """
    cr_ids = {f.id for f in cr_findings}
    tool_ids = {f.id for f in tool_findings}

    result: dict[UUID, FindingClassification] = {}

    # Which findings are paired via a Match with classification=="same"?
    matched_cr: set[UUID] = set()
    matched_tool: set[UUID] = set()
    for m in matches:
        if m.classification != "same":
            continue
        # Only care about CR ↔ tool matches (not intra-tool)
        if m.a_id in cr_ids and m.b_id in tool_ids:
            matched_cr.add(m.a_id)
            matched_tool.add(m.b_id)
        elif m.b_id in cr_ids and m.a_id in tool_ids:
            matched_cr.add(m.b_id)
            matched_tool.add(m.a_id)

    for f in cr_findings:
        result[f.id] = "agreed_with_cr" if f.id in matched_cr else "missed_from_cr"
    for f in tool_findings:
        result[f.id] = "agreed_with_cr" if f.id in matched_tool else "unique_to_tool"

    return result
