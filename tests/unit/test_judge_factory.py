"""US4 T052: Judge-Factory picks provider from env, without code changes."""
from __future__ import annotations

import pytest

from benchmark.matching.judge import AnthropicJudge, OpenAICompatJudge, make_judge


def test_factory_returns_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "sk-ant-test")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "claude-sonnet-4-5")
    j = make_judge()
    assert isinstance(j, AnthropicJudge)


def test_factory_returns_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "gpt-something")
    monkeypatch.setenv("JUDGE_LLM_BASE_URL", "https://api.openai.com/v1")
    j = make_judge()
    assert isinstance(j, OpenAICompatJudge)


def test_factory_case_insensitive_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "ANTHROPIC")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "sk-ant-test")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "claude-sonnet-4-5")
    j = make_judge()
    assert isinstance(j, AnthropicJudge)


def test_factory_defaults_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUDGE_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "sk-ant-test")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "claude-sonnet-4-5")
    j = make_judge()
    assert isinstance(j, AnthropicJudge)


def test_factory_unknown_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "cohere")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "x")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "x")
    with pytest.raises(ValueError, match="Unknown JUDGE_LLM_PROVIDER"):
        make_judge()


def test_openai_missing_base_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "x")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "x")
    monkeypatch.delenv("JUDGE_LLM_BASE_URL", raising=False)
    from benchmark.config import EnvConfigError

    with pytest.raises(EnvConfigError):
        make_judge()


def test_anthropic_accepts_optional_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """haex-claude-proxy support: Anthropic client honors a custom base_url from env."""
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "sk-ant-test")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "claude-sonnet-4-5")
    monkeypatch.setenv("JUDGE_LLM_BASE_URL", "http://localhost:8123")
    j = make_judge()
    assert isinstance(j, AnthropicJudge)
    # Underlying anthropic.Anthropic exposes the base_url on the client
    assert str(j._client.base_url).rstrip("/") == "http://localhost:8123"


def test_anthropic_no_base_url_uses_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("JUDGE_LLM_API_KEY", "sk-ant-test")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "claude-sonnet-4-5")
    monkeypatch.delenv("JUDGE_LLM_BASE_URL", raising=False)
    j = make_judge()
    assert "anthropic.com" in str(j._client.base_url)
