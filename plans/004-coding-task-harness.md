# Plan 004: Füge einen fairen Harness für Coding-Aufgaben und Agenten hinzu

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b764f88..HEAD -- pyproject.toml src tests specs coding-corpus plans`
> If the Run-Engine API, attempt contract or resource policy from Plans 001/003
> differs, stop and update this plan before implementation.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED
- **Depends on**: `plans/001-benchmark-contracts-speckit.md`, `plans/003-run-engine-resource-lease.md`
- **Category**: direction
- **Planned at**: commit `b764f88`, 2026-09-22

## Why this matters

The existing project is exclusively a reviewer pipeline: it has no task
description, starter repository, patch, sandbox or test result entity. Hermes,
OpenCode, Codex, Claude and self-hosted Qwen cannot be fairly measured by the
review-finding schema. They must get the same visible problem, a fresh isolated
workspace, explicit allowed tools and a functional oracle independent of their
own explanations.

This plan adds a second benchmark modality—coding—on the common Attempt and
Artifact contract. It prioritizes deterministic hidden tests over subjective
LLM judgement and starts with a small, representative internal suite instead
of importing a large public benchmark blindly.

## Current state

- `README.md:1-7` and `pyproject.toml:1-20` define the product as a PR-review
  benchmark; no frontend or agent runner exists.
- `src/benchmark/models.py` models `Finding`, `Match` and PR statistics only.
- Current process isolation in `src/benchmark/tools/base.py:27-62` kills process
  groups on timeout; Plan 003 expands this into per-attempt worktrees.
- Official integrations require separate treatment: Hermes can use a custom
  OpenAI-compatible endpoint and exposes lifecycle runs/events; OpenCode offers
  a CLI/JSON or server route but its config schema is versioned; both need an
  isolated home/profile to avoid memory/config contamination.
- Plan 003 establishes candidates, artifacts, worker jobs and the one-slot GPU
  resource profile that coding attempts must reuse.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Build sandbox image | `docker build -t llm-benchmark-task-python:dev sandbox/python` | Exit 0, no network-dependent test at runtime |
| Validate a task | `uv run benchmark coding validate coding-corpus/v1/<task-id>` | Public and hidden manifests validate; hidden data is not runner-visible |
| Execute oracle | `uv run benchmark coding verify --task <task-id> --revision base` | Expected baseline failure is recorded |
| Execute reference patch | `uv run benchmark coding verify --task <task-id> --revision reference` | All public and hidden checks pass |
| Runner contract tests | `uv run pytest tests/coding tests/adapters -m 'not live'` | Simulated agent attempts pass |
| Full regression | `uv run pytest && uv run ruff check .` | Entire Python suite remains green |

## Scope

**In scope**:

- New SpecKit feature `005-coding-task-harness/**`
- Versioned coding task corpus and sandbox image definitions
- Task/verification validator, CodingEvaluator and runner adapter protocol
- First adapters for the selected representatives: direct-model baseline,
  OpenCode and Hermes; external Claude/Codex adapters only after credentials and
  non-interactive contracts are confirmed
- Tests, structured events and task documentation

**Out of scope**:

- Dashboard UI, task authoring forms and multi-tenant permissions (Plan 005)
- Benchmarking arbitrary internet repositories or giving agents unrestricted
  host/Docker/socket access
- Tool-assisted code review scoring (Plan 002) and auto-generated gold labels
- Declaring a universal leader from a tiny v1 task set

## Git workflow

- Branch: create through SpecKit as `005-coding-task-harness`.
- Keep task corpus content and runner engine changes in separate commits.
- Pin runner binaries/container images and record their digests before adding a
  result to a release report.

## Steps

### Step 1: Specify coding tasks, runner visibility and objective scoring

The SpecKit feature must define the public task packet as: visible
`spec.md`/instruction, a starter repo at a pinned commit, declared commands,
time/token/resource budget, permitted filesystem/network/tool policy and public
checks. Define protected contents as hidden tests, reference patches, expected
implementation and evaluator rubrics.

Define a coding attempt outcome as: workspace patch/diff, agent event log,
command log, exit reason, public test results, protected evaluation results,
runtime/usage and a verdict. The primary score is hidden acceptance/regression
tests; report code quality, test additions, scope discipline and security policy
violations separately. An LLM critic may aid human review but cannot change a
functional pass to a fail by itself.

**Verify**: task-contract tests prove runner manifests contain neither hidden
paths nor reference-patch/expected-output content.

### Step 2: Design a small, balanced v1 task suite

Start with 20–30 owned or approved task packages across the stacks your team
cares about (proposed: Python backend and TypeScript/Nuxt frontend). Include
bug fixes, focused features, tests, refactors with behavioral protection,
cross-file changes and one dependency/API migration only when its dependencies
can be pinned offline. Stratify by estimated difficulty and context size; keep
tasks small enough for human review and deterministic CI.

Every task requires: a runnable base image, pinned base SHA, public SpecKit
requirements, a baseline test expectation, hidden acceptance/regression tests,
a reference patch or evidence of feasibility, a timeout/budget class and an
owner. Prefer realistic task history transformed into owned, de-identified
fixtures; do not make toy tasks that advertise the likely edit location.

**Verify**: corpus coverage report lists each stratum, owner, base SHA, image
digest and test status; at least one clean/no-change control validates policy.

### Step 3: Build hermetic task sandboxes and evaluators

Create versioned container images per supported language with non-root user,
read-only base input, ephemeral writable worktree, CPU/memory/PID/disk limits,
no host Docker socket and network disabled by default. Package dependency caches
inside images or through a trusted read-only mirror so verification is
reproducible. The evaluator runs after the agent exits in a new container,
not in its live process.

Use the Plan-003 artifact store to save patch, redacted event/command logs and
test reports. Test commands have individual timeouts and their exit codes are
data, not prompts. Enforce no modifications outside the mounted worktree.

**Verify**: malicious/accidental test fixtures cannot reach host paths, network
or hidden tests; evaluation still obtains the patch and deterministically
reports a timeout, test failure and policy violation.

### Step 4: Implement a neutral coding-agent adapter contract

Add a `CodingAgentAdapter` with `probe`, `prepare`, `execute`, `collect` and
`cleanup`, aligned with the ReviewAdapter from Plan 003. The executor passes a
single public task prompt and a fresh directory; it does not add tool-specific
extra hints. Normalize all runner outputs into standard events (`message`,
`tool_call`, `command`, `file_change`, `usage`, `terminal`) where available;
store unknown raw events as artifacts rather than discarding them.

Every adapter gets a private per-attempt config/home/session. Disable or wipe
Hermes memory/skills/profiles between attempts. Pin OpenCode binary and config
schema; use its versioned non-interactive JSON or server lifecycle contract.
For direct model baselines, use a deliberately minimal patch loop so the
dashboard distinguishes *model* from *agent harness* candidates. Only add
Claude/Codex once their approved API/CLI credentials and unattended invocation
contracts are documented; their non-comparable interactive subscription modes
must not be silently mixed into the matrix.

**Verify**: fake agents and each real adapter pass a smoke task with an empty
starting session; replaying the same manifest proves no persisted agent memory
or changed config is reused.

### Step 5: Execute a scientifically balanced pilot

Register each model+harness pairing as its own `CandidateVersion`. Fix or record
temperature, seed (when supported), model endpoint/server revision, context and
output limits, tools, prompt template and image digest. Run an excluded warm-up;
then execute at least three samples per candidate/task. The scheduler uses the
single `local-94gb-gpu` lease for all relevant attempts and stores queue wait
separately.

Randomize/counterbalance candidate order within difficulty strata. Do not rerun
only failed candidates until a favorable result appears; retries are distinct
attempts and remain visible. Report completion rate, test pass rate, test score,
median/p95 wall time, token/cost estimates, patch size and sandbox violations
with confidence intervals where samples allow it.

**Verify**: a pilot result query proves three immutable attempts per cell,
one active local lease maximum, excluded warm-ups and a score derived from
hidden-test results rather than agent self-report.

## Test plan

- Task packet validator: schema, SHA/image digest, public/hidden separation,
  baseline/reference behavior and corpus digest.
- Sandbox: no network/host escape, resource limit, timeout, cleanup and
  evaluator receives no agent-process state.
- Adapter: pinned probe, fresh session/home, input parity, JSON/raw event
  collection, cancellation and cleanup.
- Scoring: pass/fail, partial weighted tests when approved, regressions,
  clean-control behavior, confidence interval and no score for invalid attempts.
- Run `uv run pytest tests/coding tests/adapters && uv run pytest && uv run ruff check .`.

## Done criteria

- [ ] Approved v1 Coding suite has pinned, reproducible, hidden-oracle tasks.
- [ ] Every agent gets the same public inputs and a fresh, isolated workspace.
- [ ] Hermes and OpenCode have pinned adapter/capability contracts; direct-model
  baseline is visibly a different harness candidate.
- [ ] Functional test outcome is the primary score and all artifacts/provenance
  attach to immutable attempts.
- [ ] Local calls are serialized by the Plan-003 resource lease.
- [ ] All test/security gates pass; `plans/README.md` marks Plan 004 DONE.

## STOP conditions

- The task needs network access, a private dependency or source code that
  cannot be reproducibly isolated.
- The proposed runner cannot be made non-interactive, version-pinned or reset
  between attempts.
- A hidden test/reference patch becomes accessible to the agent through image
  layers, git objects, process environment or mounted paths.
- Functional tests are flaky across unchanged reference runs; quarantine the
  task, do not score it.

## Maintenance notes

An agent/harness pair is a candidate, not merely a provider configuration.
Keep tool permissions comparable; if a candidate requires browser/MCP/network
access, create an explicit capability tier and do not rank it directly against
offline candidates. Retire contaminated or flaky tasks through a new suite
version, never silently patch their historical oracle.
