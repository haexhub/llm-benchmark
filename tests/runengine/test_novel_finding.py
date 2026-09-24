"""FR-009a: the novel-finding judge is blind (no candidate identity in the prompt)
and its verdict is persisted separately from, never blended into, the score."""
from __future__ import annotations

from uuid import uuid4

from benchmark.matching.judge import build_blind_novel_finding_prompt
from benchmark.models import Finding
from benchmark.runengine.novel_finding import (
    propose_gold_label_candidate,
    record_novel_finding_review,
)


class _FakeVerdict:
    def __init__(self, verdict: str, reasoning: str = "looks real") -> None:
        """Initialize this test double with its simulated state."""
        self.verdict = verdict
        self.reasoning = reasoning
        self.judge_model = "test-judge"
        self.prompt_hash = "a" * 64


class _FakeCursor:
    def __init__(self, conn: _FakeConnection) -> None:
        """Initialize this test double with its simulated state."""
        self._conn = conn

    def __enter__(self) -> _FakeCursor:
        """Enter the fake database context and return its cursor."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Leave the fake database context without suppressing exceptions."""
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        """Emulate the SQL operation needed by this test."""
        self._conn.inserts.append((sql.strip().split()[2], sql, params))


class _FakeConnection:
    def __init__(self) -> None:
        """Initialize this test double with its simulated state."""
        self.inserts: list[tuple] = []

    def cursor(self) -> _FakeCursor:
        """Return a fake cursor bound to this connection."""
        return _FakeCursor(self)

    def commit(self) -> None:
        """Accept a commit without writing to a database."""
        pass


def _finding() -> Finding:
    """Build a finding for the evaluation fixture."""
    return Finding(
        id=uuid4(), tool="gito", file="service.py", line_start=1, line_end=2,
        severity="major", category="bug", title="possible bug", body="looks wrong",
    )


def test_blind_prompt_never_mentions_the_tool_name() -> None:
    """Verify blind prompt never mentions the tool name."""
    finding = _finding()

    prep = build_blind_novel_finding_prompt(finding, "demo-item")

    assert finding.tool not in prep.prompt_text
    assert "gito" not in prep.prompt_text.lower()
    assert "pr-agent" not in prep.prompt_text.lower()


def test_record_novel_finding_review_persists_the_verdict() -> None:
    """Verify record novel finding review persists the verdict."""
    conn = _FakeConnection()

    review_id = record_novel_finding_review(
        conn, evaluation_id=uuid4(), verdict=_FakeVerdict("plausible_novel_defect")
    )

    assert review_id is not None
    assert any(table == "novel_finding_review" for table, _, _ in conn.inserts)


def test_propose_gold_label_candidate_is_always_status_proposed() -> None:
    """Verify propose gold label candidate is always status proposed."""
    conn = _FakeConnection()

    candidate_id = propose_gold_label_candidate(
        conn, novel_finding_review_id=uuid4(), item_id="demo-item", finding=_finding(),
        judge_reasoning="looks real",
    )

    assert candidate_id is not None
    (_, sql, _) = next(p for p in conn.inserts if p[0] == "gold_label_candidate")
    assert "'proposed'" in sql
