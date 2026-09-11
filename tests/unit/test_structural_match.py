from __future__ import annotations

from uuid import uuid4

from benchmark.matching.structural import candidates
from benchmark.models import Finding


def _f(tool, file, start, end, **kw):
    return Finding(
        id=uuid4(),
        tool=tool,
        file=file,
        line_start=start,
        line_end=end,
        severity=kw.get("severity", "minor"),
        category=kw.get("category", "bug"),
        title=kw.get("title", "t"),
        body=kw.get("body", "b"),
    )


def test_no_candidates_different_file() -> None:
    a = _f("coderabbit", "a.py", 10, 12)
    b = _f("gito", "b.py", 10, 12)
    assert candidates([a], [b]) == []


def test_candidates_full_overlap() -> None:
    a = _f("coderabbit", "a.py", 10, 12)
    b = _f("gito", "a.py", 10, 12)
    cands = candidates([a], [b])
    assert len(cands) == 1
    assert cands[0].structural_overlap_lines > 0


def test_candidates_tolerance_boundary_at_3() -> None:
    """±3 tolerance: 10-12 vs 15-18 should NOT match (gap of 3 lines, on the edge)."""
    a = _f("coderabbit", "a.py", 10, 12)
    b = _f("gito", "a.py", 15, 18)
    cands = candidates([a], [b], tolerance=3)
    assert len(cands) == 1  # 12+3=15, 15-3=12 → they just barely touch


def test_candidates_tolerance_boundary_gap_of_4_excludes() -> None:
    a = _f("coderabbit", "a.py", 10, 12)
    b = _f("gito", "a.py", 20, 25)
    cands = candidates([a], [b], tolerance=3)
    assert cands == []


def test_same_tool_excluded_by_default() -> None:
    a = _f("gito", "a.py", 10, 12)
    b = _f("gito", "a.py", 10, 12)
    assert candidates([a], [b], same_tool_ok=False) == []


def test_same_tool_ok_includes_pairs() -> None:
    a = _f("gito", "a.py", 10, 12)
    b = _f("gito", "a.py", 10, 12)
    cands = candidates([a, b], [a, b], same_tool_ok=True)
    # (a,b) and (b,a) both emitted; self-pair excluded
    assert len(cands) == 2


def test_identical_id_excluded_from_pairs() -> None:
    a = _f("gito", "a.py", 10, 12)
    cands = candidates([a], [a], same_tool_ok=True)
    assert cands == []  # same id → skipped
