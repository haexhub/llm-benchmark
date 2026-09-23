# Feature Specification: Durable Benchmark Platform Foundation

**Feature Branch**: `002-benchmark-platform`
**Created**: 2026-09-22
**Status**: Draft
**Input**: Build a durable internal benchmark and ranking platform for coding
agents and PR-review tools. It must compare hosted and self-hosted models,
including Claude, Codex, Qwen, Hermes Agent, OpenCode, gito and PR-Agent, under
the exclusive 94-GB local-GPU constraint. The desired UI is Nuxt + Tailwind; the
current Python implementation is the starting point.

## Clarifications

### Session 2026-09-22

- Decision-grade quality comes from versioned, independently curated Ground
  Truth: hidden defect labels/reproducers for review and hidden
  acceptance/regression tests for coding. Historical CodeRabbit overlap remains
  an exploratory, separately marked panel.
- All local-inference attempts acquire `local-94gb-gpu`, whose initial capacity
  is one. Queue wait and active runtime are reported separately.
- Quality, reliability, latency and cost are primary dimensions. A weighted rank
  is optional only when its named policy version and weights are visible.
- Every execution is an immutable Attempt. Warm-ups are excluded; scored cells
  have at least three samples.
- Runners receive only public task/fixture inputs in fresh isolated worktrees.
  Hidden labels, tests, reference patches, secrets and host state are never
  mounted.
- A candidate is evaluated on two explicitly separate axes: `model_under_harness`
  (same pinned harness and capability profile across models) and
  `end_to_end_agent` (the complete model+harness+skills/tooling setup). Neither
  axis is silently merged into one ranking.
- There are no artificial SLA or "fair versus practical" budget modes. Every
  attempt has only safety ceilings to bound runaway work; actual wall time,
  queue wait, tokens, tool calls and estimated cost are benchmark KPIs.
- Every Attempt declares an immutable capability profile: filesystem rights,
  shell/test/git access, network class, MCP servers, skills bundle, memory mode
  and sub-agent policy. Comparisons either hold that profile constant or expose
  it as the independent variable.
- Suites are partitioned into development, adapter-calibration and protected
  holdout sets. Items may be sourced from approved public code, de-identified
  internal repositories, synthetic fixtures or a combination, but every release
  is reproducible and records provenance and contamination status.
- The platform also supports a continuous `live_pr_shadow` observation mode for
  opted-in GitHub repositories. For each PR revision reviewed by CodeRabbit,
  CodeRabbit is the operational baseline and gito/PR-Agent are challenger
  reviewers. This view compares findings and workflow behavior; it is distinct
  from Ground-Truth ranking.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Plan a reproducible benchmark run (Priority: P1)

An operator selects a frozen suite version, candidate versions, repetitions,
budget policy and resource profile. The system creates an immutable execution
plan and individual attempts, so the result can later be reproduced and audited.

**Why this priority**: Without stable attempts and inputs, neither reviewer
comparisons nor coding-agent rankings are trustworthy.

**Independent Test**: Create a plan with a fixture suite and two fake candidates;
inspect all manifests and verify distinct IDs, exact version references and no
hidden oracle data.

**Acceptance Scenarios**:

1. **Given** an approved suite and registered candidates, **When** an operator
   creates three repetitions, **Then** three immutable attempts per candidate/
   item cell plus a separately marked warm-up are created.
2. **Given** an existing attempt, **When** its candidate configuration changes,
   **Then** the system requires a new candidate version and does not overwrite
   the original manifest or score.

---

### User Story 2 - Queue local GPU work fairly (Priority: P1)

An operator starts local review or coding attempts without manually coordinating
GPU usage. The worker serializes them through one resource lease and records
queue wait, setup, execution and evaluation time separately.

**Why this priority**: The available GPU RAM can serve only one local model at a
time; concurrent calls distort latency, failure rate and quality comparison.

**Independent Test**: Queue three fake attempts targeting `local-94gb-gpu` and
prove that no more than one is actively executing while all outcomes are
traceable.

**Acceptance Scenarios**:

1. **Given** three queued local attempts, **When** two workers poll together,
   **Then** exactly one obtains the lease and the others remain queued.
2. **Given** a worker exits while holding a lease, **When** recovery runs,
   **Then** the attempt is safely retried or marked invalid with its reason,
   never silently scored twice.

---

### User Story 3 - Compare quality with evidence (Priority: P1)

An evaluator filters attempts by suite, language, candidate, model and policy,
then sees quality, reliability, latency and cost with sample count, uncertainty
and a drill-down to immutable evidence.

**Why this priority**: A leaderboard based on another bot's overlap or a single
favorable run would lead to the wrong infrastructure decision.

**Independent Test**: Seed attempts with known review and coding results; request
a comparison and verify Ground Truth metrics, test outcomes, failures and legacy
observations are visibly separate.

**Acceptance Scenarios**:

1. **Given** labelled review attempts, **When** an evaluator opens a comparison,
   **Then** it shows recall, precision, F1, false-positive/duplicate rate,
   completion rate and time/cost dimensions from Ground Truth.
2. **Given** coding attempts, **When** an evaluator opens a comparison, **Then**
   it shows hidden acceptance/regression test outcome as the primary metric and
   does not mix it with review scores.
3. **Given** candidates with different skills, MCP servers or tool permissions,
   **When** an evaluator compares them, **Then** the capability profile is shown
   beside every result and the evaluator can filter to a controlled profile.

---

### User Story 4 - Add benchmark material safely (Priority: P2)

A curator registers a versioned review fixture or coding task with public inputs,
protected oracle material, provenance, owner and executable validation. A runner
cannot inspect protected data.

**Why this priority**: The platform remains useful only if new models, tools and
tasks can be added without weakening scientific integrity.

**Independent Test**: Validate one fixture/task package, build its runner input
and prove that its hidden directory, reference patch and labels are absent.

**Acceptance Scenarios**:

1. **Given** a review fixture with an executable reproducer, **When** a curator
   publishes a suite version, **Then** every Gold defect has a stable ID,
   provenance and validated reproducer.
2. **Given** a coding task with public spec and hidden tests, **When** its runner
   workspace is built, **Then** protected files are unavailable while evaluation
   still runs after the agent exits.

---

### User Story 5 - Manage work from a dashboard (Priority: P2)

An authorized operator uses an internal dashboard to browse suites/candidates,
create run plans, observe queue state and inspect comparisons; a curator has
additional protected-material permissions.

**Why this priority**: The current CLI is useful for adapter diagnostics but not
for ongoing team operation or decision-making.

**Independent Test**: Use seeded data to create a plan through the UI, observe
its serial queue state and compare attempts without direct storage or runner
host access.

**Acceptance Scenarios**:

1. **Given** an authorized operator, **When** they create a run plan, **Then**
   the dashboard displays matrix size, resource class, repetitions and policy
   before submitting an idempotent request.
2. **Given** a viewer, **When** they open an attempt, **Then** they can inspect
   authorized artifacts but cannot see secrets, hidden oracle data or curator
   notes.

---

### User Story 6 - Compare every opted-in live PR with CodeRabbit (Priority: P1)

For an opted-in GitHub repository, every PR revision that CodeRabbit reviews is
also evaluated by gito and PR-Agent using the same pinned Base/Head snapshot.
The operator can inspect a single comparison that shows CodeRabbit as the
operational baseline, challenger overlap, unique findings, failures and timing.

**Why this priority**: This produces continuous evidence from the actual
projects where review tools will be used, alongside the curated benchmark suite.

**Independent Test**: Send mocked GitHub pull-request and CodeRabbit-review
events for an opted-in repository. Confirm one immutable observation per head
SHA, serialized local challenger executions and a rendered three-way comparison.

**Acceptance Scenarios**:

1. **Given** an opted-in repository and a PR opened or synchronized at head SHA
   `H`, **When** the integration receives its GitHub event, **Then** it creates
   a `live_pr_shadow` observation for `(repository, PR, base SHA, H)` and queues
   gito and PR-Agent as independent challenger attempts.
2. **Given** CodeRabbit posts review output for head SHA `H`, **When** baseline
   capture completes, **Then** the observation stores a normalized immutable
   baseline snapshot and presents matches, challenger-only findings and baseline
   findings not covered by a challenger.
3. **Given** a later commit creates head SHA `H2`, **When** it reaches the PR,
   **Then** the system creates a new observation instead of mixing comments or
   challenger outputs from `H` and `H2`.
4. **Given** CodeRabbit is delayed or does not post a review, **When** the
   configured baseline wait window expires, **Then** challengers remain visible
   but the comparison is clearly marked `baseline_incomplete`, never scored as a
   Ground-Truth result.

## Edge Cases

- A tool exits successfully but produces no parseable output: record a failed
  Attempt, not a successful zero-finding result.
- A tool's CLI/output schema changes after installation: candidate registration
  fails its capability probe until a new adapter contract is approved.
- A model server is unavailable or produces an incomplete response: retain
  artifacts and terminal reason; do not omit the attempt from reliability stats.
- A task/fixture is flaky under unchanged reference conditions: quarantine it
  from scoring and preserve evidence in a new suite revision.
- An operator submits the same plan request twice: idempotency yields one plan,
  not duplicated GPU work.
- A candidate produces a plausible finding not covered by the Gold labels: it is
  triaged blindly, human-adjudicated according to sampling/escalation policy and
  retained as an explicit unknown rather than silently counted as true or false.
- A live PR is closed, merged or superseded while its local challenger run waits
  for the GPU: retain the observation and its snapshot policy, then cancel or
  complete work according to the configured repository policy without attaching
  results to a different head SHA.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST model review and coding as separate modalities
  under shared versioned Attempt, Artifact and Evaluation contracts.
- **FR-002**: The system MUST create immutable manifests for every execution
  plan and attempt, including suite/item digest, candidate/harness/tool version,
  model/configuration hash, budgets, resource profile, timestamps and reason.
- **FR-003**: The system MUST preserve attempts, retries and warm-ups as
  separate records; it MUST NOT overwrite a prior scored result.
- **FR-004**: The system MUST schedule every local-model attempt through an
  exclusive `local-94gb-gpu` resource lease with capacity one.
- **FR-005**: The system MUST report queue wait, preparation, active execution
  and evaluation duration separately, plus actual tokens, tool calls and
  estimated cost where available. Limits are safety ceilings, not normalized SLA
  or score budgets.
- **FR-006**: The system MUST supply all candidates in a comparison cell the
  same declared visible inputs, base/head revisions, budgets and policy.
- **FR-007**: The system MUST isolate each attempt in a new workspace/session
  and prevent runners from reading hidden labels, tests, reference patches,
  credentials and host state.
- **FR-008**: The system MUST store immutable, access-scoped artifacts including
  manifest, input digest, patch/diff, normalized result, raw output, redacted
  logs and evaluator report when they exist.
- **FR-009**: Review quality MUST be evaluated against versioned Gold defects
  with executable evidence and human adjudication; CodeRabbit overlap MAY be
  displayed only as a separately marked historical observation.
- **FR-010**: Coding quality MUST be evaluated primarily by hidden executable
  acceptance/regression checks; subjective assessment MUST be secondary.
- **FR-011**: The system MUST report completion rate, quality, latency and cost
  separately with sample count and uncertainty. Any weighted rank MUST disclose
  its immutable score-policy version and weights.
- **FR-011a**: The system MUST report category-specific scorecards instead of a
  universal "best model" rank. Review categories include defect detection,
  diagnostic usefulness/noise, severity calibration, reliability and economics;
  coding categories include functional completion, regression safety, tests,
  scope/hygiene, context scale, harness leverage, reliability and economics.
- **FR-011b**: Review usefulness MUST be judged through a versioned rubric that
  separates correctness, actionability, severity calibration, redundancy and
  reviewer attention burden. A blinded frontier-model judge MAY score
  presentation/actionability, but Ground Truth and human adjudication determine
  factual correctness and all high-impact or disputed cases.
- **FR-011c**: The system MUST retain raw finding count for diagnosis but MUST
  additionally report useful high-value findings at fixed review attention
  cut-offs and a noise/attention-burden metric; a high volume of comments MUST
  NOT improve a candidate score by itself.
- **FR-012**: The system MUST version and probe every candidate tool/harness
  capability before scoring it, and reject unrecognized CLI/output drift.
- **FR-012a**: The system MUST support registering new model/harness adapters
  through a versioned adapter manifest with declared input/output contract,
  capability schema, installation/image identity, capability probe and isolated
  calibration-suite result before it may enter a scored suite.
- **FR-012b**: The system MUST persist model identity separately from harness,
  capability profile, skills bundle and endpoint/runtime configuration so that
  `model_under_harness` and `end_to_end_agent` analyses are queryable.
- **FR-013**: The system MUST expose catalog, run-plan, queue, attempt, score and
  scoped artifact operations through a typed internal API with authorized,
  auditable mutations.
- **FR-014**: The system MUST provide an internal dashboard where authorized
  users can browse suites/candidates, create or cancel plans, monitor status and
  compare attempts without direct database/object-store access.
- **FR-015**: The system MUST ensure secrets never appear in committed files,
  manifests, browser bundles, dashboard output or persisted logs.
- **FR-016**: The system MUST preserve existing `runs/` data only as incomplete
  legacy observations; it MUST NOT fabricate provenance or combine it with
  decision-grade scores.
- **FR-017**: The system MUST version suites as `development`, `calibration` or
  `holdout`. A released holdout item MUST record source/provenance, licensing or
  internal approval, content digest and contamination status; known training or
  prompt exposure retires it from decision-grade reporting.
- **FR-018**: The system MUST allow repositories to opt into a `live_pr_shadow`
  integration with an explicit GitHub event policy, CodeRabbit baseline identity,
  retention period, baseline wait window and result-publication mode.
- **FR-019**: For every observed PR revision, the system MUST persist an immutable
  tuple of repository, PR number, base SHA, head SHA, CodeRabbit baseline
  snapshot and independent challenger attempts. A later PR revision MUST create
  a new observation.
- **FR-020**: The live integration MUST run gito and PR-Agent against the same
  deterministic PR snapshot, model/runtime configuration and declared capability
  profile. They acquire the same constrained local-GPU lease sequentially.
- **FR-021**: Live PR comparison MUST distinguish `complete`,
  `baseline_waiting`, `baseline_incomplete`, `challenger_failed` and
  `superseded` states. It MUST show CodeRabbit overlap and unique findings as
  operational comparison metrics, not as decision-grade quality scores.
- **FR-022**: The default live result-publication mode MUST be private dashboard
  visibility only. Posting a summary/comment/check back to GitHub requires an
  explicit repository policy and must identify the exact PR head SHA.

### Key Entities

- **BenchmarkSuite / SuiteVersion**: A review or coding collection with
  immutable content digest, evaluator version and visibility policy.
- **BenchmarkItem**: One review fixture or coding task with public inputs,
  protected oracle material and pinned source revision.
- **Candidate / CandidateVersion**: A model plus tool/harness adapter, exact
  package/image/version capability contract and configuration identity.
- **CapabilityProfile**: Versioned set of allowed tools, network, MCP servers,
  skills, memory/session and sub-agent behavior for an Attempt.
- **SuitePartition**: Development, calibration or protected holdout classification
  plus fixture provenance and contamination status.
- **ExecutionPlan**: A frozen selected matrix, repetitions, budgets, order and
  score/resource policy.
- **Attempt**: One candidate version × item sample with lifecycle, provenance,
  timings and terminal result.
- **ResourceProfile / ResourceLease**: Named limited execution capacity and its
  auditable exclusive assignment.
- **Artifact**: Content-addressed output with retention and access class.
- **DefectLabel**: Protected review Ground Truth with taxonomy, severity,
  evidence and adjudication history.
- **Evaluation / ScorePolicy**: Versioned computed evidence and transparent
  aggregate metrics.
- **UsefulnessAssessment**: Blinded rubric result for a review finding, with
  correctness source, actionability, calibration, redundancy and attention cost.
- **RepositoryIntegration**: Opt-in live repository configuration, GitHub event
  identity, baseline provider identity, wait/retention and publication policy.
- **LivePRObservation**: Immutable operational comparison for one repository,
  PR and Base/Head revision pair, linking baseline snapshot and challenger
  attempts.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of scored attempts have non-empty suite, candidate,
  model/configuration, evaluator, policy, timestamp and artifact digest fields;
  repeating a cell creates separate attempt IDs.
- **SC-002**: Under a three-attempt contention test, no more than one attempt
  using `local-94gb-gpu` executes concurrently; queued attempts reach a terminal
  audited state or explicit operator-visible blockage.
- **SC-003**: A released review suite has 100% executable/reviewed Gold defects
  and at least 20% clean negative controls; released coding tasks have 100%
  deterministic reference verification over five unchanged executions.
- **SC-004**: Every published comparison shows sample count, completion rate,
  quality metrics, p50/p95 execution time, queue wait and cost/usage
  availability; results from different modality, comparison axis, capability
  profile or policy are not silently aggregated.
- **SC-005**: Runner-input inspection finds zero hidden oracle files, reference
  patches or secret values, while post-run evaluation completes.
- **SC-006**: An authorized operator can create a plan and observe queued/running
  state in the dashboard without shell/database/object-storage access; every
  mutation has an audit actor and idempotency key.
- **SC-007**: 100% of scored candidates pass their adapter calibration suite and
  carry a versioned capability profile; all published views distinguish controlled
  model comparisons from end-to-end agent comparisons.
- **SC-008**: For a mocked opted-in PR lifecycle with two head revisions, the
  system creates exactly two distinct live observations; every challenger result
  and CodeRabbit snapshot belongs to its matching head SHA and local challengers
  never overlap in active execution.

## Assumptions

- The platform runs on internal infrastructure and may retain approved benchmark
  artifacts internally; exact retention and SSO integration are deployment ADRs.
- Python remains the worker/control-plane language; FastAPI, PostgreSQL and
  S3-compatible internal artifact storage are proposed for later feature plans.
- The frontend is Nuxt 3 with Tailwind and consumes typed control-plane APIs.
- Initial decision-grade v1 suites target Python and TypeScript/Nuxt; additional
  languages are versioned corpus expansions.
- Every v1 suite has a small public development partition, a non-ranking adapter
  calibration partition and a protected holdout partition. Fixture source may be
  public, internal or synthetic if provenance and reproducibility are recorded.
- Existing local endpoints are OpenAI-compatible and one endpoint/model is
  available at a time within the 94-GB resource profile.
- External APIs are evaluated only with approved credentials and exact runner/
  invocation versions recorded.
