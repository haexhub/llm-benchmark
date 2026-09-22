"""Private, operational-only rendering for one immutable live observation."""

from __future__ import annotations

from collections.abc import Mapping

from benchmark.models import Finding

from .observations import CodeRabbitSnapshot, LiveObservationStore, LivePRSnapshot
from .scheduler import LiveChallengerResult


def render_live_observation(
    observation: LivePRSnapshot,
    baseline: CodeRabbitSnapshot | None,
    challenger_results: Mapping[str, LiveChallengerResult],
) -> str:
    """Render findings and terminal states without claiming benchmark quality scores."""
    lines = [
        f"# Live PR shadow review — {observation.repository}#{observation.pr_number}",
        "",
        "Operational only — not a Gold score.",
        "",
        "## Immutable revision",
        "",
        f"- Base SHA: `{observation.base_sha}`",
        f"- Head SHA: `{observation.head_sha}`",
        f"- Diff SHA-256: `{observation.diff_sha256}`",
        "",
        "## CodeRabbit baseline",
        "",
    ]
    if baseline is None:
        lines.extend(["Baseline unavailable for this exact Head SHA.", ""])
    else:
        lines.extend(_render_findings(baseline.findings))

    for challenger in ("gito", "pr-agent"):
        lines.extend([f"## {challenger}", ""])
        result = challenger_results.get(challenger)
        if result is None:
            lines.extend([f"{challenger}: not run", ""])
            continue
        attempt = result.attempt
        lines.append(f"{challenger}: {attempt.state} ({attempt.duration_seconds:.2f}s)")
        if attempt.error:
            lines.append(f"Error: `{_escape(attempt.error)}`")
        lines.append("")
        if result.findings is not None:
            lines.extend(_render_findings(result.findings))

    return "\n".join(lines).rstrip() + "\n"


def render_stored_live_observation(store: LiveObservationStore, observation: LivePRSnapshot) -> str:
    """Render only artifacts already captured for one immutable observation."""
    return render_live_observation(
        observation,
        store.load_coderabbit_snapshot(observation),
        {
            challenger: result
            for challenger in ("gito", "pr-agent")
            if (result := store.load_challenger_result(observation, challenger)) is not None
        },
    )


def _render_findings(findings: tuple[Finding, ...] | list[Finding]) -> list[str]:
    if not findings:
        return ["No findings.", ""]
    lines: list[str] = []
    for finding in findings:
        lines.append(
            f"- **{_escape(finding.file)}:{finding.line_start}-{finding.line_end}** "
            f"({finding.severity}/{finding.category}): {_escape(finding.title)}"
        )
    lines.append("")
    return lines


def _escape(value: str) -> str:
    return value.replace("`", "'").replace("\n", " ")
