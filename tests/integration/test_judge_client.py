"""Judge-client integration tests.

Live tests hitting real Anthropic/OpenAI-compat endpoints are gated behind
`-m live` (opt-in). All non-live tests use a Fake or exercise the JSON parser.
"""
from __future__ import annotations

import pytest

from benchmark.matching.judge import _parse_verdict


def test_parse_verdict_plain_json() -> None:
    v = _parse_verdict('{"same": true, "confidence": 0.85, "reason": "same loop bound"}', "m", "0" * 64)
    assert v.same is True
    assert v.confidence == pytest.approx(0.85)


def test_parse_verdict_wrapped_in_fence() -> None:
    raw = '```json\n{"same": false, "confidence": 0.9, "reason": "different files"}\n```'
    v = _parse_verdict(raw, "m", "0" * 64)
    assert v.same is False


def test_parse_verdict_extra_text_around() -> None:
    raw = "Here you go: {\"same\": true, \"confidence\": 0.7, \"reason\": \"x\"} — done."
    v = _parse_verdict(raw, "m", "0" * 64)
    assert v.same is True
    assert v.confidence == pytest.approx(0.7)


def test_parse_verdict_invalid_json_raises() -> None:
    with pytest.raises(ValueError):
        _parse_verdict("not JSON at all", "m", "0" * 64)


@pytest.mark.live
def test_anthropic_judge_live_ping() -> None:
    """Live-check: only runs when explicitly invoked with `pytest -m live`."""
    from uuid import uuid4

    from benchmark.matching.judge import AnthropicJudge
    from benchmark.models import Finding

    j = AnthropicJudge()
    a = Finding(id=uuid4(), tool="coderabbit", file="a.py", line_start=10, line_end=12, severity="major", category="bug", title="off by one", body="loop range too small")
    b = Finding(id=uuid4(), tool="gito", file="a.py", line_start=10, line_end=12, severity="major", category="bug", title="loop bound wrong", body="range(n) should be range(n+1)")
    verdict = j.evaluate_pair(a, b, pr_context="test")
    assert verdict.judge_model
    assert 0.0 <= verdict.confidence <= 1.0
