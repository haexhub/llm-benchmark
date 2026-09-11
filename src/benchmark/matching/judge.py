"""Judge client — decides whether two Findings describe the same defect.

Two SDK-backed implementations:
- `AnthropicJudge` via the `anthropic` SDK (Claude Sonnet default)
- `OpenAICompatJudge` via the `openai` SDK against any OpenAI-compatible endpoint

Blind presentation (FR-009):
- Findings are labeled A/B; the order is deterministic-random per (pr_id, finding_pair) hash.
- Tool names are NOT included in the prompt.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Protocol

from benchmark.config import env, require_env
from benchmark.models import Finding, JudgeVerdict

log = logging.getLogger("benchmark.judge")


JUDGE_INSTRUCTIONS = (
    "You are evaluating whether two AI code review findings describe the SAME underlying defect "
    "in the SAME piece of code. You must answer strictly as a JSON object matching the schema:\n"
    '{"same": true|false, "confidence": 0.0-1.0, "reason": "short explanation"}\n'
    "'same' means: a developer fixing one would also fix the other; they point at the same root cause. "
    "Different wording, different suggested fix, different severity does not disqualify them.\n"
    "Never include any text outside the JSON."
)


class JudgeClient(Protocol):
    """Every Judge implementation resolves a Finding pair to a Verdict."""

    def evaluate_pair(
        self, a: Finding, b: Finding, *, pr_context: str
    ) -> JudgeVerdict: ...


@dataclass
class _BlindPresentation:
    prompt_text: str
    prompt_hash: str
    a_is_first: bool


def build_blind_prompt(a: Finding, b: Finding, pr_context: str) -> _BlindPresentation:
    """Anonymize + deterministically randomize A/B order per (pr_context, finding_ids)."""
    key = f"{pr_context}|{a.id}|{b.id}"
    digest = hashlib.sha256(key.encode()).digest()
    a_is_first = (digest[0] & 1) == 0
    first, second = (a, b) if a_is_first else (b, a)

    def _describe(f: Finding, label: str) -> str:
        return (
            f"[{label}]\n"
            f"  file:   {f.file}\n"
            f"  lines:  {f.line_start}-{f.line_end}\n"
            f"  severity (per own tool): {f.severity}\n"
            f"  title:  {f.title}\n"
            f"  body:   {f.body}\n"
            + (f"  suggestion: {f.suggestion}\n" if f.suggestion else "")
        )

    body = (
        f"{JUDGE_INSTRUCTIONS}\n\n"
        f"Finding pair for PR context {pr_context!r}:\n\n"
        f"{_describe(first, 'A')}\n"
        f"{_describe(second, 'B')}\n"
        f"Answer only with the JSON object."
    )
    return _BlindPresentation(
        prompt_text=body,
        prompt_hash=hashlib.sha256(body.encode()).hexdigest(),
        a_is_first=a_is_first,
    )


def _parse_verdict(raw: str, model: str, prompt_hash: str) -> JudgeVerdict:
    text = raw.strip()
    # Strip common LLM fluff (fenced blocks)
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    # Try to locate the first {...} block
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("judge returned non-JSON: %s", raw[:200])
        raise ValueError(f"judge output not JSON: {exc}") from exc
    return JudgeVerdict(
        same=bool(obj.get("same")),
        confidence=float(obj.get("confidence", 0.0)),
        reason=str(obj.get("reason", "")),
        judge_model=model,
        prompt_hash=prompt_hash,
    )


class AnthropicJudge:
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        from anthropic import Anthropic

        self.model = model or require_env("JUDGE_LLM_MODEL")
        self._client = Anthropic(api_key=api_key or require_env("JUDGE_LLM_API_KEY"))

    def evaluate_pair(self, a: Finding, b: Finding, *, pr_context: str) -> JudgeVerdict:
        prep = build_blind_prompt(a, b, pr_context)
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=400,
            temperature=0,
            messages=[{"role": "user", "content": prep.prompt_text}],
        )
        # anthropic 0.34+: response.content is a list of content blocks
        parts = getattr(resp, "content", [])
        text = "".join(getattr(p, "text", "") for p in parts).strip()
        return _parse_verdict(text, self.model, prep.prompt_hash)


class OpenAICompatJudge:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        from openai import OpenAI

        self.model = model or require_env("JUDGE_LLM_MODEL")
        self._client = OpenAI(
            api_key=api_key or require_env("JUDGE_LLM_API_KEY"),
            base_url=base_url or require_env("JUDGE_LLM_BASE_URL"),
        )

    def evaluate_pair(self, a: Finding, b: Finding, *, pr_context: str) -> JudgeVerdict:
        prep = build_blind_prompt(a, b, pr_context)
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=400,
            temperature=0,
            messages=[{"role": "user", "content": prep.prompt_text}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        return _parse_verdict(text, self.model, prep.prompt_hash)


def make_judge() -> JudgeClient:
    provider = (env("JUDGE_LLM_PROVIDER", "anthropic") or "anthropic").lower()
    if provider == "anthropic":
        return AnthropicJudge()
    if provider == "openai":
        return OpenAICompatJudge()
    raise ValueError(f"Unknown JUDGE_LLM_PROVIDER: {provider!r} (use 'anthropic' or 'openai')")
