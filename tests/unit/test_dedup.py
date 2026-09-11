from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from benchmark.matching.dedup import dedup_intra_tool
from benchmark.models import Finding, JudgeVerdict


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


@dataclass
class FakeJudge:
    same_pairs: set = field(default_factory=set)  # set of frozensets of finding ids
    confidence: float = 0.9
    calls: int = 0

    def evaluate_pair(self, a, b, *, pr_context: str) -> JudgeVerdict:
        self.calls += 1
        key = frozenset({a.id, b.id})
        same = key in self.same_pairs
        return JudgeVerdict(
            same=same,
            confidence=self.confidence,
            reason="fake",
            judge_model="fake",
            prompt_hash="a" * 64,
        )


def test_dedup_removes_confirmed_duplicate() -> None:
    a = _f("gito", start=10)
    b = _f("gito", start=11)  # overlaps with a
    fake = FakeJudge(same_pairs={frozenset({a.id, b.id})})
    deduped, dup_count = dedup_intra_tool([a, b], fake, pr_context="x")
    assert dup_count == 1
    assert len(deduped) == 1


def test_dedup_keeps_different_findings() -> None:
    a = _f("gito", start=10)
    b = _f("gito", start=11)
    fake = FakeJudge(same_pairs=set())  # judge says NOT same
    deduped, dup_count = dedup_intra_tool([a, b], fake, pr_context="x")
    assert dup_count == 0
    assert len(deduped) == 2


def test_dedup_skips_cross_tool_pairs() -> None:
    a = _f("gito", start=10)
    b = _f("pr-agent", start=11)  # different tool → not intra-tool
    fake = FakeJudge(same_pairs=set())
    deduped, dup_count = dedup_intra_tool([a, b], fake, pr_context="x")
    assert dup_count == 0
    assert len(deduped) == 2
    assert fake.calls == 0  # judge never invoked (no intra-tool candidates)


def test_dedup_low_confidence_keeps_both() -> None:
    a = _f("gito", start=10)
    b = _f("gito", start=11)
    fake = FakeJudge(same_pairs={frozenset({a.id, b.id})}, confidence=0.4)  # below default 0.6
    deduped, dup_count = dedup_intra_tool([a, b], fake, pr_context="x")
    assert dup_count == 0
    assert len(deduped) == 2


def test_dedup_empty_input() -> None:
    fake = FakeJudge()
    assert dedup_intra_tool([], fake, pr_context="x") == ([], 0)
