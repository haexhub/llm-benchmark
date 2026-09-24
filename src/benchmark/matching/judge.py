"""Judge client — decides whether two Findings describe the same defect, and
(specs/005-run-engine-adapters FR-009a) whether a single finding not covered
by any Gold label looks like a plausible novel defect.

Two SDK-backed implementations:
- `AnthropicJudge` via the `anthropic` SDK (Claude Sonnet default)
- `OpenAICompatJudge` via the `openai` SDK against any OpenAI-compatible endpoint

Blind presentation (FR-009):
- Findings are labeled A/B; the order is deterministic-random per (pr_id, finding_pair) hash.
- Tool names are NOT included in the prompt.

Novel-finding review (FR-009a) reuses the same blinding discipline (no tool
name in the prompt) for a single finding, never the sole ranking truth for a
candidate's score (constitution Principle II) — see runengine/novel_finding.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Literal, Protocol

from benchmark.config import env, require_env
from benchmark.models import Finding, JudgeVerdict

log = logging.getLogger("benchmark.judge")

NovelFindingVerdictLabel = Literal["plausible_novel_defect", "not_defect", "inconclusive"]


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


@dataclass(frozen=True)
class NovelFindingVerdict:
    verdict: NovelFindingVerdictLabel
    reasoning: str
    judge_model: str
    prompt_hash: str


NOVEL_FINDING_INSTRUCTIONS = (
    "You are reviewing a single code-review finding that did not match any of "
    "this fixture's known, pre-verified defects. Decide whether it still looks "
    "like a real, plausible defect the fixture's authors simply didn't "
    "anticipate, or whether it looks incorrect or too vague to act on. "
    "Answer strictly as a JSON object matching the schema:\n"
    '{"verdict": "plausible_novel_defect"|"not_defect"|"inconclusive", '
    '"reasoning": "short explanation"}\n'
    "'plausible_novel_defect' means a developer would reasonably act on this. "
    "'not_defect' means it is wrong, a style nit dressed up as a defect, or "
    "already addressed. 'inconclusive' means you cannot tell without more "
    "context than is given here.\n"
    "Never include any text outside the JSON."
)


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
        """Render one anonymized finding under its assigned label."""
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


def build_blind_novel_finding_prompt(finding: Finding, item_context: str) -> _BlindPresentation:
    """Anonymize a single finding for novel-defect review — no tool name included."""
    body = (
        f"{NOVEL_FINDING_INSTRUCTIONS}\n\n"
        f"Finding for fixture item {item_context!r}:\n\n"
        f"  file:   {finding.file}\n"
        f"  lines:  {finding.line_start}-{finding.line_end}\n"
        f"  title:  {finding.title}\n"
        f"  body:   {finding.body}\n"
        + (f"  suggestion: {finding.suggestion}\n" if finding.suggestion else "")
        + "Answer only with the JSON object."
    )
    return _BlindPresentation(
        prompt_text=body, prompt_hash=hashlib.sha256(body.encode()).hexdigest(), a_is_first=True
    )


def _parse_novel_finding_verdict(raw: str, model: str, prompt_hash: str) -> NovelFindingVerdict:
    """Parse and validate the judge response for a novel finding."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("novel-finding judge returned non-JSON: %s", raw[:200])
        raise ValueError(f"judge output not JSON: {exc}") from exc
    verdict = obj.get("verdict")
    if verdict not in ("plausible_novel_defect", "not_defect", "inconclusive"):
        raise ValueError(f"judge returned an unrecognized verdict: {verdict!r}")
    return NovelFindingVerdict(
        verdict=verdict,
        reasoning=str(obj.get("reasoning", "")),
        judge_model=model,
        prompt_hash=prompt_hash,
    )


def _parse_verdict(raw: str, model: str, prompt_hash: str) -> JudgeVerdict:
    """Parse the judge response for a pair of findings."""
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
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Configure the Anthropic client and judge model from arguments or the environment."""
        from anthropic import Anthropic

        self.model = model or require_env("JUDGE_LLM_MODEL")
        resolved_base = base_url if base_url is not None else env("JUDGE_LLM_BASE_URL")
        client_kwargs = {"api_key": api_key or require_env("JUDGE_LLM_API_KEY")}
        if resolved_base:
            client_kwargs["base_url"] = resolved_base
        self._client = Anthropic(**client_kwargs)

    def evaluate_pair(self, a: Finding, b: Finding, *, pr_context: str) -> JudgeVerdict:
        """Ask Anthropic whether two blinded findings describe one defect."""
        prep = build_blind_prompt(a, b, pr_context)
        # No `temperature` param: verified live against anthropic==1.5.0, whose
        # Messages.create() signature no longer accepts it at all (TypeError,
        # not a server rejection) — likely moot anyway when routed through a
        # CLI-wrapping proxy (e.g. haex-claude-proxy), which has no sampling
        # knob to forward it to. Judge-run determinism is therefore best-effort
        # (see research.md), not guaranteed.
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=400,
            messages=[{"role": "user", "content": prep.prompt_text}],
        )
        # anthropic 0.34+: response.content is a list of content blocks
        parts = getattr(resp, "content", [])
        text = "".join(getattr(p, "text", "") for p in parts).strip()
        return _parse_verdict(text, self.model, prep.prompt_hash)

    def evaluate_novel_finding(self, finding: Finding, *, item_context: str) -> NovelFindingVerdict:
        """Ask Anthropic to assess a blinded potential novel defect."""
        prep = build_blind_novel_finding_prompt(finding, item_context)
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=400,
            messages=[{"role": "user", "content": prep.prompt_text}],
        )
        parts = getattr(resp, "content", [])
        text = "".join(getattr(p, "text", "") for p in parts).strip()
        return _parse_novel_finding_verdict(text, self.model, prep.prompt_hash)


class OpenAICompatJudge:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Configure an OpenAI-compatible client and judge model."""
        from openai import OpenAI

        self.model = model or require_env("JUDGE_LLM_MODEL")
        self._client = OpenAI(
            api_key=api_key or require_env("JUDGE_LLM_API_KEY"),
            base_url=base_url or require_env("JUDGE_LLM_BASE_URL"),
        )

    def evaluate_pair(self, a: Finding, b: Finding, *, pr_context: str) -> JudgeVerdict:
        """Ask the OpenAI-compatible judge to compare two blinded findings."""
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

    def evaluate_novel_finding(self, finding: Finding, *, item_context: str) -> NovelFindingVerdict:
        """Ask the OpenAI-compatible judge to assess a blinded novel finding."""
        prep = build_blind_novel_finding_prompt(finding, item_context)
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=400,
            temperature=0,
            messages=[{"role": "user", "content": prep.prompt_text}],
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        return _parse_novel_finding_verdict(text, self.model, prep.prompt_hash)


def make_judge() -> JudgeClient:
    """Create the configured provider for pairwise finding judgments."""
    provider = (env("JUDGE_LLM_PROVIDER", "anthropic") or "anthropic").lower()
    if provider == "anthropic":
        return AnthropicJudge()
    if provider == "openai":
        return OpenAICompatJudge()
    raise ValueError(f"Unknown JUDGE_LLM_PROVIDER: {provider!r} (use 'anthropic' or 'openai')")


def make_novel_finding_judge() -> AnthropicJudge | OpenAICompatJudge:
    """Like `make_judge()`, but pinned to `NOVEL_DEFECT_JUDGE_MODEL` when set
    (falls back to `JUDGE_LLM_MODEL`) so novel-finding review can use a
    different, typically stronger model than pair-matching (FR-009a)."""
    provider = (env("JUDGE_LLM_PROVIDER", "anthropic") or "anthropic").lower()
    model = env("NOVEL_DEFECT_JUDGE_MODEL") or None
    if provider == "anthropic":
        return AnthropicJudge(model=model)
    if provider == "openai":
        return OpenAICompatJudge(model=model)
    raise ValueError(f"Unknown JUDGE_LLM_PROVIDER: {provider!r} (use 'anthropic' or 'openai')")
