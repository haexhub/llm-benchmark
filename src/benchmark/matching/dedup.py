"""Intra-tool deduplication: LLM-Judge fuses duplicate findings within the same tool."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from uuid import UUID

from benchmark.matching.judge import JudgeClient
from benchmark.matching.structural import candidates
from benchmark.models import Finding

log = logging.getLogger("benchmark.dedup")


def dedup_intra_tool(
    findings: Iterable[Finding],
    judge: JudgeClient,
    *,
    pr_context: str,
    confidence_threshold: float = 0.6,
    tolerance: int = 3,
) -> tuple[list[Finding], int]:
    """Return (deduped_findings, num_duplicates_folded).

    When two findings of the same tool structurally overlap and the judge says
    `same` with high confidence, we drop the second occurrence.
    """
    all_findings = list(findings)
    if len(all_findings) < 2:
        return all_findings, 0

    # Group per tool to keep the O(n²) small
    by_tool: dict[str, list[Finding]] = {}
    for f in all_findings:
        by_tool.setdefault(f.tool, []).append(f)

    dropped: set[UUID] = set()
    dup_count = 0
    for tool, group in by_tool.items():
        if len(group) < 2:
            continue
        cands = candidates(group, group, tolerance=tolerance, same_tool_ok=True)
        # Deduplicate the (a, b) vs (b, a) mirror
        seen_pairs: set[frozenset[UUID]] = set()
        for cand in cands:
            key = frozenset({cand.a_id, cand.b_id})
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            if cand.a_id in dropped or cand.b_id in dropped:
                continue
            a = next(f for f in group if f.id == cand.a_id)
            b = next(f for f in group if f.id == cand.b_id)
            try:
                verdict = judge.evaluate_pair(a, b, pr_context=f"{pr_context}#dedup:{tool}")
            except Exception as exc:  # noqa: BLE001
                log.warning("dedup judge failed on %s/%s: %s", a.id, b.id, exc)
                continue
            if verdict.same and verdict.confidence >= confidence_threshold:
                dropped.add(b.id)
                dup_count += 1

    deduped = [f for f in all_findings if f.id not in dropped]
    return deduped, dup_count
