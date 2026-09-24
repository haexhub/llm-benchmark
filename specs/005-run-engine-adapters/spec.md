# Feature Specification: Run Engine and Adapters

**Feature Branch**: `005-run-engine-adapters`
**Created**: 2026-09-24
**Status**: Draft

## Clarifications

### Session 2026-09-24

- Q: What does "reproducible" mean for SC-003, given gito/pr-agent call an LLM? → A: Reproducibility applies to plan/attempt manifest identity and the evaluator's classification logic (deterministic given the same recorded findings), not to bit-identical LLM output across runs. The input/setup (suite version, item fixtures, candidate version, policy) is guaranteed identical; the LLM-driven result is not, which is exactly why repetitions exist.
- Q: How do an item's repeated attempts (e.g. 3 repetitions) combine into a candidate's aggregate recall/precision/F1? → A: Every attempt is its own independent sample — repetitions increase sample count, they are not reduced to one per-item vote first. Aggregate metrics must also surface the observed spread (min–max range) across repetitions, not just a single averaged number, so a candidate that found 1/2/3 defects across three repeated runs of the same item shows that variance instead of hiding it behind an average.
- Q: Does this feature include a human-adjudication workflow for disputed/unmatched-gold findings? → A: No human in the loop. Automatic Oracle-matching classification is the complete deliverable for decision-grade scoring. Separately, every `unmatched_gold` finding (a candidate reported something not on the corpus's verified Gold list — i.e. a possible bug the corpus authors missed) is additionally reviewed by a blinded frontier-model judge (Claude Opus 5 initially), which labels it `plausible_novel_defect`, `not_defect` or `inconclusive`. That judge verdict and its count/rate are reported as a separate, clearly-marked panel next to the score — it MUST NOT change recall/precision/F1/completion-rate, which stay 100% Oracle-based, so the decision-grade score is never partly determined by one LLM's opinion (constitution Principle II: an LLM judge may assist triage but must not be the sole ranking truth).
- Q: Should `plausible_novel_defect` findings feed back into the corpus's Gold label set? → A: Yes, as candidates only — never automatically, and never retroactively into the suite version the finding was scored under (constitution Principle I: no result may be overwritten to improve a score). 005 packages each as a Gold-label candidate for the curator; promotion into an actual Gold label reuses 003's existing curator-approval and reproducer-validation pipeline and always produces a new suite version.
- Q: Should this feature also retrofit feature 004's existing live-PR-shadow scheduler onto the new shared resource lease? → A: Originally answered yes (retrofit as part of 005's delivery). Superseded during planning: `src/benchmark/live/resource_lease.py` (`SqliteResourceLeaseStore`) already implements a durable, cross-process, TTL-based, crash-recoverable exclusive lease, and both the existing `benchmark run` pipeline and feature 004's live challenger runner already acquire it from the same store under the same `local-94gb-gpu` resource key — confirmed by reading `src/benchmark/live/runner.py` and `src/benchmark/pipeline.py`, not just `scheduler.py` as done during the original clarification. No feature-004 code changes are needed; 005 only needs to acquire from that same existing store.
- Q: On a transient shared-endpoint failure, does the engine auto-retry? → A: Yes, bounded automatic retry (default 3 attempts, each its own new immutable Attempt, never overwriting the failed one) for transient/connection-class failures only; non-transient failures (bad output schema, candidate crash) never auto-retry. The retry cap is adjustable at runtime through the same CLI/API surface as plan creation — not a graphical settings page, which would reopen the no-dashboard boundary (FR-014); a UI for it can live in feature 007 later.

**Input**: User description: "Run Engine and Adapters: build the execution platform from
specs/002-benchmark-platform/plan.md delivery slice 2 (originally planned as feature 004,
superseded in numbering by 004-live-pr-shadow-review). Scope per plan.md: PostgreSQL-backed
immutable attempts, S3-compatible artifact storage, exclusive single-GPU lease scheduling,
fair isolated worktrees per attempt, and version-pinned gito/pr-agent adapters. This engine
must execute the version-pinned gito and pr-agent tools against every item in the
review-ground-truth corpus (specs/003-review-ground-truth-corpus, published at
haexhub/llm-benchmark-review-corpus with private oracle at haexhub/llm-benchmark-review-oracle),
record immutable per-attempt manifests and artifacts per the Attempt/Artifact contracts already
defined in specs/002-benchmark-platform/data-model.md and contracts/, and produce decision-grade
scores per constitution Principle II (Independent Ground Truth) and Principle V (Transparent
Scores and Versioned Policy) by matching tool findings against the protected Oracle defect
labels. Must not build the Nuxt dashboard (that is a separate later feature,
007-benchmark-control-plane-ui per plan.md) or the coding-task harness (006). Must respect
Principle III (equal isolated candidate conditions) and Principle IV (resource-aware
scheduling)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the review corpus through a candidate and get a reproducible plan (Priority: P1)

An operator selects a released Ground-Truth review-corpus suite version and one or more
registered review-tool candidate versions (gito, pr-agent), sets a repetition count, and starts
a run. The system creates one immutable execution plan and one immutable attempt per
candidate-version/item/repetition cell, executes each candidate against the item's Base/Head
fixture in a fresh isolated workspace, and persists every attempt's manifest and artifacts so the
run can be reproduced and audited later.

**Why this priority**: Without a reproducible, immutable plan and attempt record, no comparison
that follows can be trusted or re-derived — this is the foundation everything else in this
feature builds on.

**Independent Test**: Create a plan against a small corpus suite version with the gito and
pr-agent candidates and two repetitions; inspect the persisted plan and attempts and verify
distinct attempt IDs, exact suite/candidate version references, and that no protected Oracle
file is present in any attempt's recorded input digest.

**Acceptance Scenarios**:

1. **Given** a released corpus suite version and two registered candidate versions, **When** an
   operator starts a plan with three repetitions, **Then** the system creates three immutable
   attempts per candidate/item cell, each with its own manifest, and no attempt overwrites
   another's manifest or result.
2. **Given** an existing plan, **When** the operator re-submits the identical plan request,
   **Then** the system returns the existing plan instead of creating duplicate attempts or
   duplicate executions.
3. **Given** a corpus item with a Base/Head fixture, **When** an attempt executes, **Then** the
   candidate only receives the item's public fixture files in a dedicated fresh workspace, and
   the attempt's recorded input digest contains no Oracle ground-truth or reproducer file.

---

### User Story 2 - Queue candidate executions fairly on the shared local endpoint (Priority: P1)

An operator starts a run without manually coordinating with other work already using the shared
local model endpoint (including concurrently running live-PR-shadow challenger attempts). The
engine serializes every attempt that targets that endpoint through one exclusive resource lease
and records queue wait, setup, execution and evaluation time separately.

**Why this priority**: The shared local endpoint can serve only one caller at a time; unmanaged
concurrency distorts latency, causes spurious timeouts and makes quality differences
unattributable to the candidate itself.

**Independent Test**: Queue attempts from two different plans (or one plan and one live-PR-shadow
observation) targeting the same resource profile at once; prove that no more than one is actively
executing at any time while every attempt still reaches a terminal, audited state.

**Acceptance Scenarios**:

1. **Given** several queued attempts targeting the same exclusive resource, **When** two workers
   poll at the same time, **Then** exactly one attempt obtains the lease and the others remain
   queued.
2. **Given** a worker process exits while holding a lease, **When** lease recovery runs, **Then**
   the attempt is either safely retried or marked `invalid` with a recorded reason — it is never
   silently scored twice and never left holding a stale lease indefinitely.
3. **Given** a running execution plan and a concurrently arriving live-PR-shadow challenger
   attempt, **When** both target the same resource profile, **Then** they are serialized through
   the same lease rather than executing in parallel.

---

### User Story 3 - See decision-grade quality scores per candidate (Priority: P1)

An evaluator opens a completed run and sees, per candidate version, how its findings compare
against the corpus's protected Oracle defect labels: recall, precision, F1, false-positive rate,
duplicate rate, completion rate, and per-attempt latency/cost — with sample count and enough
attempts to say the result isn't a fluke. Every score is tied to the exact suite version,
candidate version and score-policy version that produced it.

**Why this priority**: This is the actual purpose of the feature — turning tool executions into
a trustworthy, decision-grade quality comparison, not just a pile of raw output.

**Independent Test**: Run a small suite version with a candidate whose findings are known against
its Oracle labels ahead of time; request the comparison and verify every classification outcome
(matched, duplicate, false-positive, insufficient-evidence, unmatched-Gold) and every reported
metric matches hand-computed expectations.

**Acceptance Scenarios**:

1. **Given** completed attempts for a candidate version against a suite version, **When** an
   evaluator requests its score, **Then** the system reports recall, precision, F1,
   false-positive rate, duplicate rate and completion rate, each with sample count, alongside the
   exact suite-version digest and score-policy version used.
2. **Given** two candidate versions run against the same suite version, **When** an evaluator
   compares them, **Then** each candidate's operational metrics (queue wait, execution time,
   tokens/cost where available) are shown separately from its quality metrics — never blended
   into one number without a named, versioned weighting.
3. **Given** an attempt whose candidate produced no parseable output, **When** the run completes,
   **Then** the attempt is recorded as failed with its terminal reason, and it is excluded from
   quality scoring but included in completion-rate and reliability reporting.
4. **Given** a candidate reported findings beyond the suite's known Gold defects, **When** an
   evaluator opens the comparison, **Then** a separate panel shows, per candidate version, the
   count of `unmatched_gold` findings the blinded judge rated `plausible_novel_defect`, distinct
   from and never added into the Oracle-based recall/precision/F1.

---

### User Story 4 - Register and gate a review-tool candidate version safely (Priority: P2)

An operator registers a new or updated version of a review-tool candidate (a new gito or
pr-agent release, or a new model/endpoint configuration behind one of them) with its exact
version identity. The system probes its capability/output contract before allowing it into a
scored run, and rejects it if its CLI or output schema has drifted from what the adapter expects.

**Why this priority**: Silently scoring a candidate whose output the parser can no longer
understand would either crash runs or — worse — silently produce wrong, unnoticed scores.

**Independent Test**: Register a candidate version pointing at a deliberately incompatible tool
build; attempt to start a plan with it and verify the plan is rejected with a clear reason before
any attempt executes.

**Acceptance Scenarios**:

1. **Given** a new candidate version with declared tool/package identity, **When** it is
   registered, **Then** the system runs its capability probe and only marks it usable in a scored
   plan if the probe succeeds.
2. **Given** a candidate version whose installed tool now emits an unrecognized output shape,
   **When** an attempt tries to parse its result, **Then** the attempt is marked `invalid` with
   that reason rather than silently scored as zero findings.

### Edge Cases

- A candidate process exits successfully but its output file is missing or unparseable: recorded
  as a failed/invalid attempt, never as a zero-finding success.
- Two attempts target the same corpus item and candidate version in the same plan (repetitions):
  each keeps its own sample index and manifest; none is overwritten.
- The shared local endpoint is unreachable for an attempt already holding the lease: the attempt
  ends in a terminal failed/timed-out state and releases the lease; it does not hang and block
  every other queued attempt indefinitely. If the failure is transient/connection-class, a fresh
  retry Attempt is created automatically up to the configured cap (FR-013a); once the cap is
  exhausted, the last attempt stays terminally failed.
- An operator submits an identical plan request twice (same suite version, candidate versions,
  repetitions, resource/score policy): the system returns the one existing plan, not a duplicate.
- A corpus item is later revised (new bundle digest) after a plan already referenced its previous
  version: the existing plan and its attempts keep referencing the old, pinned item version; nothing
  is retroactively rewritten.
- An execution-plan attempt and a `live_pr_shadow` challenger attempt (feature
  004-live-pr-shadow-review) contend for the same exclusive resource at the same time: they
  already serialize through the existing shared `SqliteResourceLeaseStore`, since both acquire
  the same `local-94gb-gpu` resource key from the same store.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST create an immutable execution plan for a chosen corpus suite
  version, one or more registered review-tool candidate versions, a repetition count and a
  resource/score policy, and MUST return the same plan on an identical repeated request
  (idempotency).
- **FR-002**: The system MUST create one immutable Attempt per candidate-version/item/repetition
  cell, each with its own manifest recording suite-version digest, item ID, candidate-version ID,
  capability profile, resource profile, budget, timestamps and a terminal reason once finished.
- **FR-003**: The system MUST NOT overwrite a previously created or scored Attempt; retries and
  repetitions MUST always create new Attempt records.
- **FR-004**: The system MUST execute every Attempt that targets a shared local model endpoint
  through an exclusive resource lease with a configured fixed capacity, serialized against all
  other work (including `live_pr_shadow` challenger attempts) that targets the same resource.
- **FR-004a**: This feature's batch-attempt execution MUST acquire the exclusive resource lease
  from the same durable lease store and resource key (`local-94gb-gpu`) that feature 004's live
  challenger runner and the existing `benchmark run` pipeline already use, so batch corpus
  attempts and live challenger attempts are provably serialized through the one lease already in
  production use. No change to feature 004's own code is required for this.
- **FR-005**: The system MUST record queue wait, workspace preparation, active execution and
  evaluation duration separately for every Attempt, plus tokens/tool-call counts and estimated
  cost where the candidate or endpoint reports them.
- **FR-006**: The system MUST give every candidate version in the same plan the same declared
  visible item input (the item's public Base/Head fixture), the same budget ceiling and the same
  execution/capability policy.
- **FR-007**: The system MUST execute each Attempt in a fresh, isolated workspace materialized
  from the item's public fixture only; the protected Oracle repository's ground-truth labels,
  reproducers and any other hidden material MUST NOT be reachable from that workspace.
- **FR-008**: The system MUST persist immutable, access-scoped Artifacts for every Attempt,
  including its manifest, input digest, the candidate's raw output, its normalized findings, and
  an evaluator report once evaluation runs.
- **FR-009**: The system MUST evaluate every Attempt's normalized findings against the suite's
  protected Oracle defect labels, classifying each into `matched`, `duplicate`, `false_positive`,
  `insufficient_evidence` or `unmatched_gold`.
- **FR-009a**: The system MUST additionally submit every `unmatched_gold` finding to a blinded
  frontier-model judge (the judge MUST NOT be told which candidate produced the finding), which
  labels it `plausible_novel_defect`, `not_defect` or `inconclusive`. The judge's verdict and its
  count/rate per candidate version MUST be reported as a distinct panel next to the Oracle-based
  score; it MUST NOT alter recall, precision, F1 or completion-rate, which remain computed solely
  from Oracle matches.
- **FR-009b**: The system MUST make every `plausible_novel_defect` verdict available as a
  Gold-label *candidate* (item ID, location, the finding, the judge's reasoning) for curator
  review. It MUST NOT promote a candidate into a scored Gold label automatically, and MUST NOT
  retroactively change the Gold set of a suite version that attempts have already scored against.
  Promoting a candidate into a Gold label follows the existing 003 curator-approval and
  reproducer-validation pipeline and always produces a new suite version.
- **FR-010**: The system MUST compute and report, per candidate version and suite version, recall,
  precision, F1, false-positive rate, duplicate rate and completion rate, each with sample count
  and observed spread (min–max range) across repetitions, tied to an explicit, versioned
  score-policy identity. Every attempt — including each repetition of the same item — counts as
  its own independent sample; repetitions are never reduced to a single per-item verdict before
  aggregation.
- **FR-011**: The system MUST report operational metrics (queue wait, execution time, tokens,
  cost) separately from quality metrics for every candidate version; it MUST NOT combine them into
  one ranking number except through a named, versioned, disclosed score policy.
- **FR-012**: The system MUST register each review-tool candidate version with its exact
  tool/package version identity and run a capability probe before that version may be used in a
  scored plan; a failed probe MUST block the version from scored use until re-probed successfully.
- **FR-013**: The system MUST reject or invalidate an Attempt whose candidate output no longer
  matches its adapter's expected schema, recording the drift as the attempt's terminal reason
  rather than silently treating it as zero findings.
- **FR-013a**: On a transient failure of the shared local endpoint (timeout, connection reset),
  the system MUST automatically create a bounded number of fresh retry Attempts (default 3,
  each its own new immutable Attempt record, never overwriting the failed one). The retry cap
  MUST be adjustable at runtime through the same CLI/API surface as plan creation, without a code
  change or redeploy. Non-transient failures (bad output schema, candidate crash) MUST NOT
  auto-retry.
- **FR-014**: The system MUST expose plan creation, attempt status and score results through an
  internal, auditable interface (CLI and/or typed API); it MUST NOT require a graphical dashboard
  to create a plan or read a result.
- **FR-015**: The system MUST keep this engine's execution plans and attempts (batch corpus runs)
  and feature 004's `live_pr_shadow` observations as distinct record types that may share resource
  leases but MUST NOT be merged into one another's identity or scoring.
- **FR-016**: The system MUST ensure no secret (API key, endpoint credential) is written into a
  committed file, manifest, artifact or log.

### Key Entities

- **ExecutionPlan**: A frozen selection of one corpus suite version, one or more candidate
  versions, repetition count, resource policy and score-policy version; idempotent per identical
  request.
- **Attempt**: One candidate-version × corpus-item × repetition execution, with lifecycle status,
  manifest, timings and terminal result; never overwritten.
- **CandidateVersion**: A registered, exact-versioned review-tool build (gito or pr-agent) plus its
  model/endpoint configuration identity and capability-probe result.
- **ResourceProfile / ResourceLease**: The shared local endpoint's named capacity and its
  auditable exclusive per-attempt assignment; this feature reuses the existing
  `SqliteResourceLeaseStore` and `local-94gb-gpu` resource key already shared with feature 004's
  live challenger attempts and the legacy `benchmark run` pipeline.
- **Artifact**: A content-addressed, access-scoped output of an Attempt (manifest, raw output,
  normalized findings, evaluator report).
- **Evaluation**: The classification of one Attempt's findings against the suite's protected
  Oracle labels, plus computed metrics tied to a score-policy version.
- **NovelFindingReview**: A blinded frontier-model judge's verdict (`plausible_novel_defect`/
  `not_defect`/`inconclusive`) on one `unmatched_gold` finding; reported separately from, and never
  blended into, the Oracle-based score.
- **GoldLabelCandidate**: A `plausible_novel_defect` finding packaged for curator review (item,
  location, finding, judge reasoning); promotable only by a human curator, via 003's existing
  approval pipeline, into a new suite version — never into the suite version it was found under.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of created attempts have a non-empty suite version, candidate version, manifest
  digest and timestamp; repeating an identical plan request never creates a second plan or
  duplicate attempts.
- **SC-002**: Under a contention test of at least three simultaneous attempts targeting the shared
  exclusive resource, no more than one executes at a time, and every attempt reaches a terminal,
  audited state.
- **SC-003**: A full run of both candidates against the released 102-item corpus produces, for
  each candidate version, a recall/precision/F1 score with its sample count and exact score-policy
  version. A second identical run against the same pinned suite version produces the same plan
  identity, the same set of attempt manifests and the same classification logic applied to
  whatever findings each run's attempts recorded — it is not required to produce bit-identical
  scores, since the candidates call an LLM and repetitions exist precisely to sample that
  variance rather than assume it away.
- **SC-004**: Runner-input inspection of any Attempt's workspace finds zero protected Oracle files
  (ground-truth labels, reproducers) at any point before or during execution.
- **SC-005**: Every reported comparison separates quality, completion rate, latency and cost, and
  never displays a combined rank without naming its score-policy version and weights.
- **SC-006**: An operator can create a plan and read its attempts' status and final scores through
  the CLI/API alone, without direct database or object-storage access.
- **SC-007**: For a run where a candidate reports at least one finding outside the Gold set, the
  comparison surfaces its judge-reviewed `plausible_novel_defect` count without changing that
  candidate's recall/precision/F1, and the finding is retrievable as a Gold-label candidate record.

## Assumptions

- This feature covers the `review` modality only, against the existing
  003-review-ground-truth-corpus suite; the `coding` modality and its harness are out of scope
  (feature 006).
- No graphical dashboard is built in this feature; plan creation, status and score inspection are
  CLI/API-only. The Nuxt dashboard is feature 007 and will read the same persisted data later.
- CodeRabbit is not a candidate in this engine's decision-grade scoring; the corpus's own Oracle
  labels are the Ground Truth. CodeRabbit-overlap comparisons remain scoped to feature
  004-live-pr-shadow-review's operational view.
- Candidate versions in scope are gito and pr-agent, using the existing `TOOL_LLM_*`-configured
  OpenAI-compatible endpoint; that endpoint is the "shared local model endpoint" referenced by
  FR-004 and is the same one feature 004's live challenger attempts already use.
- PostgreSQL is used for plan/attempt/candidate/score state and an S3-compatible store for
  content-addressed artifacts, per specs/002-benchmark-platform/plan.md; exact deployment/hosting
  choices are implementation-level decisions for the plan phase, not this specification.
- A minimum of three repetitions (samples) per candidate/item cell is the default for a scored
  run, consistent with specs/002-benchmark-platform's existing clarification; an operator may
  request more.
- Existing `matching/aggregator.py` classification logic (matched/duplicate/false_positive/
  insufficient_evidence/unmatched_gold) is the starting point for FR-009's evaluator and is
  expected to be adapted, not redesigned from scratch.
- The blinded frontier-model judge (FR-009a) is a hosted API call (Claude Opus 5 initially,
  reachable independently of the `TOOL_LLM_*` shared local endpoint); its own latency/cost is
  recorded like any other operational metric but never affects the resource lease in FR-004.
- Gold-label-candidate promotion (FR-009b) is out of scope for this feature's own delivery — it
  reuses 003's already-built curator-approval/reproducer pipeline; 005 only needs to produce the
  candidate record in a format that pipeline can consume.
