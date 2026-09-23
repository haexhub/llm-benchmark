# ADR 002: Comparison Axes, Suite Partitions and Review Usefulness

**Status**: Accepted, 2026-09-22

## Decision

The platform publishes category scorecards, never one universal best-model rank.
Each result belongs to one of two comparison axes:

1. `model_under_harness`: identical pinned harness and CapabilityProfile,
   varying model/runtime only.
2. `end_to_end_agent`: intentionally different model, harness, skills, MCP,
   memory and tool configurations.

Attempts use only safety ceilings and report actual time, queue wait, tokens,
tool calls and cost. No artificial fair/practical SLA tracks are created.

Suites have `development`, non-ranking `calibration` and protected `holdout`
partitions. Approved public, internal and synthetic fixtures are all valid when
their provenance, reproducibility and contamination status are recorded.

Review usefulness is not raw comment volume. Ground Truth/human adjudication
establish factual correctness. A pinned blinded frontier judge may score
actionability, clarity and severity calibration with a stable rubric; disputed,
high-severity and sampled unknown findings go to human adjudication.

## Consequences

The dashboard must make comparison axis and CapabilityProfile prominent.
Adapters need manifest/probe/calibration contracts. Review reports retain raw
counts for diagnosis but prioritize useful high-value findings and attention
burden. Holdout refresh and contamination tracking are continuing curator work.

Live project PRs form a separate `live_pr_shadow` lane: CodeRabbit is its
operational baseline, and Gito/PR-Agent findings are compared at the same PR
head SHA. This lane is useful for day-to-day tool observation but is not merged
with Ground-Truth rankings. The initial publication mode is dashboard-only to
avoid adding unsolicited bot noise to active PRs.
