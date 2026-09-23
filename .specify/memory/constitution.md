# LLM Benchmark Constitution

## Core Principles

### I. Reproducibility and Immutable Provenance (NON-NEGOTIABLE)

Every scored attempt MUST reference immutable versions of its suite item,
candidate/harness, model configuration, evaluator and resource policy. The
system MUST retain a manifest and hashes for the inputs and produced artifacts.
Retries are separate attempts; no result may be overwritten to improve a score.

### II. Independent Ground Truth (NON-NEGOTIABLE)

Quality rankings MUST be evaluated against independently curated ground truth:
hidden executable defect labels for review and hidden acceptance/regression tests
for coding. A candidate's self-report, an LLM judge or overlap with another
reviewer may assist triage but MUST NOT be the sole ranking truth.

### III. Equal, Isolated Candidate Conditions (NON-NEGOTIABLE)

Candidates within a comparison cell MUST receive the same declared visible
input, budget, base revision and execution policy. Each attempt MUST use a fresh
isolated workspace and session/profile. Hidden labels, tests, reference patches,
credentials and host state MUST NOT be accessible to a runner.

### IV. Resource-Aware and Honest Measurement

Every local model endpoint MUST be scheduled through an explicit resource
profile. Capacity constraints, queue wait, setup time, runner time, evaluation
time, completion state, token usage and estimated cost MUST be recorded
separately where available. A single local GPU resource MAY NOT be oversubscribed
for a scientific comparison.

### V. Transparent Scores and Versioned Policy

The primary reports MUST show quality, reliability, latency and cost separately,
including sample size and uncertainty. A total ranking MAY exist only through a
named, versioned score policy with disclosed weights. Scores from different
suite, evaluator or policy versions MUST NOT be silently combined.

### VI. Secure Internal Operation

Secrets MUST remain in approved secret stores or runtime environment injection;
they MUST NOT be committed, displayed in the dashboard, written to manifests or
persisted in raw logs. Artifact access MUST be role-scoped and auditable. New
runner integrations require explicit network, filesystem and credential bounds.

## Benchmark Boundaries

- The decision-grade suite consists of owned or approved, versioned benchmark
  fixtures. Historical PRs and CodeRabbit observations are an explicitly marked
  exploratory realism panel, never the sole quality rank.
- Each local inference server is represented by a named resource profile. The
  current `local-94gb-gpu` profile has capacity one unless the operator changes
  the documented hardware policy.
- New candidate, harness, model, prompt/configuration, evaluator or fixture
  revision creates a new versioned identity.
- The initial platform supports review and coding modalities. Cross-modality
  metrics are not comparable and must not share one numeric leaderboard.

## Development Workflow and Quality Gates

1. Every material change starts in a SpecKit feature with a reviewed `spec.md`,
   plan, data model, contracts and tasks.
2. Contracts and migration paths are tested before workers or UI consumers.
3. New behavior follows test-first development: introduce a failing focused test,
   implement the smallest change, then refactor under the full regression suite.
4. Worker, sandbox, adapter and API changes require unit plus integration tests;
   real external endpoints remain opt-in live tests.
5. Before merging, run the documented lint, type, unit, integration and relevant
   contract checks. Record deviations and rationale in the active feature.
6. Any exception to a NON-NEGOTIABLE principle requires an explicit, dated ADR
   approved by the operator before implementation; it cannot be inferred from a
   code comment or local configuration.

## Governance

This constitution supersedes repository conventions where they conflict. Amend
it through a SpecKit clarification, a migration/compatibility plan and explicit
operator approval. Every feature plan's Constitution Check MUST state how its
scope satisfies these principles.

**Version**: 1.0.0 | **Ratified**: 2026-09-22 | **Last Amended**: 2026-09-22
