"""FR-009 verification: Judge sees pairs blind (no tool names, deterministic-random order)."""
from __future__ import annotations

from uuid import UUID

from benchmark.matching.judge import build_blind_prompt
from benchmark.models import Finding


def _f(tool, fid_hex, file="a.py") -> Finding:
    """Content is deliberately tool-agnostic so the blind-check tests only fail on real leakage."""
    return Finding(
        id=UUID(fid_hex),
        tool=tool,
        file=file,
        line_start=10,
        line_end=12,
        severity="major",
        category="bug",
        title="Broad exception handler",
        body="The except clause is too broad and swallows the traceback.",
    )


def test_prompt_never_names_the_tool() -> None:
    a = _f("coderabbit", "11111111-1111-1111-1111-111111111111")
    b = _f("gito", "22222222-2222-2222-2222-222222222222")
    prep = build_blind_prompt(a, b, pr_context="alice/repo#42")
    assert "coderabbit" not in prep.prompt_text.lower()
    assert "gito" not in prep.prompt_text.lower()
    assert "pr-agent" not in prep.prompt_text.lower()
    # Labels A/B are used
    assert "[A]" in prep.prompt_text
    assert "[B]" in prep.prompt_text


def test_ordering_is_deterministic_per_context() -> None:
    a = _f("coderabbit", "11111111-1111-1111-1111-111111111111")
    b = _f("gito", "22222222-2222-2222-2222-222222222222")
    prep1 = build_blind_prompt(a, b, pr_context="alice/repo#42")
    prep2 = build_blind_prompt(a, b, pr_context="alice/repo#42")
    assert prep1.a_is_first == prep2.a_is_first
    assert prep1.prompt_hash == prep2.prompt_hash


def test_ordering_varies_across_pr_contexts() -> None:
    """Signal test: not every PR should produce the same ordering."""
    a = _f("coderabbit", "11111111-1111-1111-1111-111111111111")
    b = _f("gito", "22222222-2222-2222-2222-222222222222")
    orderings = {
        build_blind_prompt(a, b, pr_context=f"repo#{n}").a_is_first
        for n in range(30)
    }
    assert orderings == {True, False}, "ordering should vary across pr_context values"


def test_prompt_hash_stable_shape() -> None:
    a = _f("coderabbit", "11111111-1111-1111-1111-111111111111")
    b = _f("gito", "22222222-2222-2222-2222-222222222222")
    prep = build_blind_prompt(a, b, pr_context="x")
    assert len(prep.prompt_hash) == 64
    assert all(c in "0123456789abcdef" for c in prep.prompt_hash)
