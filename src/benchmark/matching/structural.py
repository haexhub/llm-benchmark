"""Structural pre-filter: which Finding pairs overlap enough to warrant Judge evaluation?"""
from __future__ import annotations

from collections.abc import Iterable

from benchmark.models import Finding, MatchCandidate


def candidates(
    findings_a: Iterable[Finding],
    findings_b: Iterable[Finding],
    tolerance: int = 3,
    same_tool_ok: bool = False,
) -> list[MatchCandidate]:
    """Return pairs of findings that share a file and have overlapping line ranges.

    - `tolerance`: N lines of gap that still count as "overlapping" (default ±3).
    - `same_tool_ok`: if False, only cross-tool pairs are candidates (Cross-Tool matching);
      if True (used for intra-tool dedup), pairs of same tool are also emitted.
    """
    findings_a = list(findings_a)
    findings_b = list(findings_b)
    results: list[MatchCandidate] = []
    for a in findings_a:
        for b in findings_b:
            if a.id == b.id:
                continue
            if not same_tool_ok and a.tool == b.tool:
                continue
            if a.file != b.file:
                continue
            overlap = _overlap_lines(
                a.line_start, a.line_end, b.line_start, b.line_end, tolerance
            )
            if overlap > 0:
                results.append(
                    MatchCandidate(
                        a_id=a.id,
                        b_id=b.id,
                        a_tool=a.tool,
                        b_tool=b.tool,
                        structural_overlap_lines=overlap,
                    )
                )
    return results


def _overlap_lines(a_start: int, a_end: int, b_start: int, b_end: int, tol: int) -> int:
    """Number of lines that both ranges cover after expanding each by `tol`."""
    a_lo = a_start - tol
    a_hi = a_end + tol
    b_lo = b_start - tol
    b_hi = b_end + tol
    lo = max(a_lo, b_lo)
    hi = min(a_hi, b_hi)
    if hi < lo:
        return 0
    return hi - lo + 1
