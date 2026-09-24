# Tasks: Run Engine and Adapters

**Input**: Design documents from `/specs/005-run-engine-adapters/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Included. The constitution's Development Workflow (item 3–4) requires
test-first development and unit+integration tests for worker/adapter/API
changes — not optional for this feature.

**Organization**: Tasks are grouped by user story (spec.md priorities) to
enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an
  incomplete task in this list)
- **[Story]**: US1–US4, per spec.md
- `-m db` tests require `docker compose up -d postgres minio` (quickstart.md)

---

## Phase 1: Setup

- [x] T001 Create `docker-compose.yml` at repo root with `postgres` and `minio` services (research.md R5)
- [x] T002 [P] Add `psycopg[binary]>=3.2` and `boto3>=1.34` to `pyproject.toml` dependencies
- [x] T003 [P] Add a `db` pytest marker and change default `addopts` to `-m 'not live and not db'` in `pyproject.toml`
- [x] T004 [P] Extend `.env.example` with `RUNENGINE_DATABASE_URL`, `RUNENGINE_S3_ENDPOINT_URL`/`_BUCKET`/`_ACCESS_KEY`/`_SECRET_KEY` and `NOVEL_DEFECT_JUDGE_MODEL`

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T005 Write migration `0001_initial.sql` (`candidate_version`, `execution_plan`, `attempt`, `score`, `evaluation`, `novel_finding_review`, `gold_label_candidate` tables per data-model.md) in `src/benchmark/runengine/migrations/0001_initial.sql`
- [x] T008 [P] Author the unit test that will verify the migration runner applies `0001_initial.sql` idempotently, in `tests/runengine/test_db.py`; execute it after T006
- [x] T009 [P] Author the `db`-marked integration test that will verify `db.py` connects/migrates and `artifacts.py` round-trips a blob against the docker-compose stack, in `tests/integration/test_runengine_infra.py`; execute it after T006 and T007
- [x] T006 Implement the psycopg connection helper + migration runner in `src/benchmark/runengine/db.py` (depends on T005 and the test authored in T008)
- [x] T007 [P] Implement S3-compatible content-addressed artifact put/get in `src/benchmark/runengine/artifacts.py` (depends on the test authored in T009)
- [x] T010 Mount an empty `runengine_app` Typer sub-app (`app.add_typer(runengine_app, name="runengine")`) in `src/benchmark/cli.py`

**Checkpoint**: Foundation ready — user stories can now proceed.

---

## Phase 3: User Story 1 - Run the review corpus through a candidate and get a reproducible plan (Priority: P1) 🎯 MVP

**Goal**: Create an immutable execution plan and one immutable, manifest-backed
Attempt per candidate/item/repetition cell; execute a candidate against the
item's fixture in a fresh, Oracle-free workspace.

**Independent Test**: Create a plan against a small suite version with the
gito and pr-agent candidates and two repetitions; inspect the persisted plan
and attempts for distinct IDs and zero Oracle files in any recorded input
digest (per spec.md's Independent Test for US1).

### Tests for User Story 1

- [x] T011 [P] [US1] Unit test: an identical plan request returns the existing plan instead of creating a duplicate, in `tests/runengine/test_plan.py`
- [x] T012 [P] [US1] Unit test: attempt manifest fields (`is_warmup=false`, `comparison_axis="end_to_end_agent"`, matches `specs/002-benchmark-platform/contracts/attempt-manifest.schema.json`) and fresh-workspace Oracle isolation, in `tests/runengine/test_attempts.py`
- [x] T013 [P] [US1] Unit test: subprocess `RunResult` timeout and connection/timeout text on stderr map to a retryable terminal reason, while unknown child failures and schema drift do not; verify a transient failure creates a new retry Attempt up to the configured cap and a non-transient failure never retries, in `tests/runengine/test_retry.py`
- [x] T014 [P] [US1] Contract test: a plan request built by `plan.py` validates against `contracts/execution-plan-request.schema.json`, in `tests/runengine/test_contracts.py`

### Implementation for User Story 1

- [x] T015 [US1] Implement `ExecutionPlan` creation with idempotency-key lookup in `src/benchmark/runengine/plan.py` (depends on T006)
- [x] T016 [US1] Create one `Attempt` row (+ manifest) per candidate × item × repetition in `src/benchmark/runengine/attempts.py` (depends on T015)
- [x] T017 [US1] Materialize a fresh workspace from the item's public fixture only, reusing `benchmark.corpus.materialize_review_input`, in `src/benchmark/runengine/attempts.py` (depends on T016)
- [x] T018 [US1] Execute the candidate (reusing `tools/gito.py` + `tools/pr_agent.py`) and persist raw output / normalized findings as Artifacts, in `src/benchmark/runengine/attempts.py` (depends on T017, T007)
- [x] T019 [US1] Implement transient-vs-non-transient classification (research.md R9) and bounded automatic retry (default 3, runtime-configurable) in `src/benchmark/runengine/retry.py` (depends on T018)
- [x] T020 [US1] CLI: `runengine plan create` in `src/benchmark/cli.py` (depends on T015)
- [x] T021 [US1] CLI: `runengine plan run` in `src/benchmark/cli.py` (depends on T019)
- [x] T022 [US1] CLI: `runengine attempt list` / `runengine attempt show` in `src/benchmark/cli.py` (depends on T016)
- [x] T023 [US1] `db`-marked integration test: `plan create` → `plan run` end-to-end with a stubbed candidate executor; verify distinct manifests and zero Oracle files in any workspace, in `tests/integration/test_runengine_plan.py` (depends on T020, T021)

Implementation note: a minimal `candidate.py` (bare `register_candidate`/`get_candidate`,
no probe gating yet) was added ahead of schedule — US1 cannot create an Attempt without
a `candidate_version` row to reference (FK). US4 (T042/T043) adds the actual
capability-probe gate on top of this same table.

**Checkpoint**: User Story 1 is fully functional and independently testable (MVP).

---

## Phase 4: User Story 2 - Queue candidate executions fairly on the shared local endpoint (Priority: P1)

**Goal**: Serialize every Attempt targeting the shared local endpoint through
the existing exclusive `local-94gb-gpu` lease, recording timing separately.

**Independent Test**: Queue attempts from two different plans (or one plan
and one live-PR-shadow observation) targeting the same resource at once;
prove no more than one executes at a time and every attempt reaches a
terminal, audited state.

### Tests for User Story 2

- [x] T024 [P] [US2] Unit test: of several attempts contending for `local-94gb-gpu`, only one executes at a time, in `tests/runengine/test_lease_integration.py`
- [x] T025 [P] [US2] Unit test: recovery fences the prior attempt or confirms its endpoint handles are closed before reclaiming an expired lease, then retries or invalidates without double-scoring, in `tests/runengine/test_lease_recovery.py`

### Implementation for User Story 2

- [x] T026 [US2] Acquire/renew/release through the existing `SqliteResourceLeaseStore` — same `runs/run-engine.sqlite3` file and `local-94gb-gpu` key already used by `pipeline.py` and `live/runner.py` (research.md R3) — maintain an independent heartbeat during candidate execution; if renewal returns `False`, terminate the candidate subprocess/process group and mark the Attempt failed; recovery must fence the prior process group or confirm its endpoint handles are closed before takeover — in `src/benchmark/runengine/attempts.py` (depends on T018)
- [x] T027 [US2] Record `queued_at`/`leased_at`/`started_at`/`evaluated_at`/`finished_at` separately per Attempt in `src/benchmark/runengine/attempts.py` (depends on T026)
- [x] T028 [US2] `db`-marked integration test: a runengine Attempt and a simulated feature-004 live-challenger attempt both targeting `local-94gb-gpu` never execute concurrently, in `tests/integration/test_runengine_shared_lease.py` (depends on T026)

Implementation note (T026): renews the lease once before the (synchronous,
blocking) tool call rather than heartbeating from a background thread during
it — marked with a `ponytail:` comment in attempts.py. Safe only because
`LEASE_TTL_SECONDS` (3600s) comfortably exceeds the default execution timeout
(1800s); `run_attempt` now raises if a caller ever passes `timeout >=
LEASE_TTL_SECONDS`, so this assumption can't silently stop holding. A true
mid-execution heartbeat with subprocess-group termination is the upgrade path
if a future candidate needs a longer per-attempt timeout.
T028's test doesn't actually need Postgres/MinIO (pure SQLite lease file), so
it isn't `-m db`-marked despite the task text — see the test file's docstring.

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: User Story 3 - See decision-grade quality scores per candidate (Priority: P1)

**Goal**: Classify every Attempt's findings against the corpus Oracle,
compute recall/precision/F1/false-positive-rate/duplicate-rate/completion-rate
per candidate, and surface Opus-judged novel findings in a separate,
non-scoring panel.

**Independent Test**: Run a small suite version with a candidate whose
findings are known against its Oracle labels ahead of time; request the
comparison and verify every classification outcome and every reported metric
matches hand-computed expectations.

### Tests for User Story 3

- [ ] T029 [P] [US3] Unit test: evaluator classifies `matched`/`duplicate`/`false_positive`/`insufficient_evidence`/`unmatched_gold` against known Oracle labels, in `tests/runengine/test_evaluator.py`
- [ ] T030 [P] [US3] Unit test: scoring aggregates recall/precision/F1/false-positive-rate/duplicate-rate/completion-rate with sample count and min–max range across repetitions, treating every repetition as an independent sample, in `tests/runengine/test_scoring.py`
- [ ] T031 [P] [US3] Unit test: `evaluate_novel_finding` presents blindly (no candidate identity in the prompt) and its verdict never changes computed metrics, in `tests/runengine/test_novel_finding.py`
- [ ] T032 [P] [US3] Contract test: a built score report validates against `contracts/score-report.schema.json`, with `novel_findings` never folded into `metrics`, in `tests/runengine/test_contracts.py`

### Implementation for User Story 3

- [ ] T033 [P] [US3] Adapt `matching/aggregator.py`'s classification logic against the corpus Oracle's `ground-truth.yaml` labels in `src/benchmark/runengine/evaluator.py` (depends on T018)
- [ ] T034 [P] [US3] Add `evaluate_novel_finding()` to `src/benchmark/matching/judge.py`, reusing `build_blind_prompt`/`_parse_verdict`, with `NOVEL_DEFECT_JUDGE_MODEL` falling back to `JUDGE_LLM_MODEL` (research.md R4)
- [ ] T035 [US3] Persist `NovelFindingReview` rows and create `GoldLabelCandidate` rows (`status="proposed"` only) for `plausible_novel_defect` verdicts, in `src/benchmark/runengine/novel_finding.py` (depends on T034)
- [ ] T036 [P] [US3] Compute per-candidate/suite/policy `Score` rows from independent per-attempt samples with min–max spread, in `src/benchmark/runengine/scoring.py` (depends on T033)
- [ ] T037 [US3] CLI: `runengine score show` in `src/benchmark/cli.py` (depends on T036)
- [ ] T038 [US3] CLI: `runengine gold-candidates export` in `src/benchmark/cli.py` (depends on T035)
- [ ] T039 [US3] `db`-marked integration test: end-to-end plan run against a small fixture suite with known Oracle labels; verify the score report matches hand-computed recall/precision/F1, in `tests/integration/test_runengine_scoring.py` (depends on T037, T023)

**Checkpoint**: US1+US2+US3 — the decision-grade comparison is usable end-to-end.

---

## Phase 6: User Story 4 - Register and gate a review-tool candidate version safely (Priority: P2)

**Goal**: Register a candidate version with a capability probe; block scored
use on a failed probe; invalidate (never silently zero-score) an attempt
whose output schema has drifted.

**Independent Test**: Register a candidate version pointing at a deliberately
incompatible tool build; verify plan creation is rejected with a clear reason
before any attempt executes.

### Tests for User Story 4

- [ ] T040 [P] [US4] Unit test: a candidate version with a failing capability probe cannot be referenced by `plan create`, in `tests/runengine/test_candidate.py`
- [ ] T041 [P] [US4] Unit test: an unrecognized candidate output schema marks the Attempt `invalid` without triggering an auto-retry, in `tests/runengine/test_attempts.py`

### Implementation for User Story 4

- [ ] T042 [P] [US4] Implement `CandidateVersion` registration + capability probe, reusing `check()`'s reachability logic (research.md R8), in `src/benchmark/runengine/candidate.py` (depends on T006)
- [ ] T043 [US4] Reject plan creation referencing a `candidate_version` whose probe status isn't `passed`, in `src/benchmark/runengine/plan.py` (depends on T042, T015)
- [ ] T044 [US4] CLI: `runengine candidate register` in `src/benchmark/cli.py` (depends on T042)
- [ ] T045 [P] [US4] Detect adapter output schema drift, set `terminal_reason="invalid"`, and exclude it from `retry.py`'s transient set, in `src/benchmark/runengine/attempts.py` (depends on T018)

**Checkpoint**: All four user stories are independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T046 [P] Run `quickstart.md` end-to-end against the local docker-compose stack; fix any drift
- [ ] T047 [P] Full verification: `uv run pytest && uv run pytest -m db && uv run ruff check .` all exit 0

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup — blocks all user stories.
- **US1 (Phase 3)**: Depends on Foundational only. This is the MVP.
- **US2 (Phase 4)**: Depends on Foundational + US1's T018 (needs a running Attempt to lease around); independently testable per its own Independent Test.
- **US3 (Phase 5)**: Depends on Foundational + US1's T018 (needs recorded findings to classify); independently testable per its own Independent Test.
- **US4 (Phase 6)**: Depends on Foundational + US1's T015/T018; independently testable per its own Independent Test.
- **Polish (Phase 7)**: Depends on all four user stories.

Note: US2, US3 and US4 all build on US1's Attempt-execution primitive
(T018) rather than on each other — they can proceed in parallel once US1's
core loop exists, matching spec.md's framing of US1 as "the foundation
everything else in this feature builds on."

### Parallel Opportunities

- Setup: T002, T003, T004 in parallel.
- Foundational: author T008 and T009 before T006/T007; execute T008 after T006 and T009 after T006/T007.
- US1 tests: T011–T014 in parallel.
- US2 tests: T024, T025 in parallel.
- US3 tests: T029–T032 in parallel; T033, T034, T036 in parallel (independent modules; T035 depends on T034).
- US4: T040, T041 in parallel; T042, T045 in parallel.

---

## Parallel Example: User Story 1 tests

```bash
Task: "Unit test: identical plan request returns the existing plan in tests/runengine/test_plan.py"
Task: "Unit test: attempt manifest fields + workspace isolation in tests/runengine/test_attempts.py"
Task: "Unit test: bounded retry vs. no-retry classification in tests/runengine/test_retry.py"
Task: "Contract test: execution-plan-request.schema.json in tests/runengine/test_contracts.py"
```

---

## Implementation Strategy

### MVP First

1. Phase 1 (Setup) → Phase 2 (Foundational) → Phase 3 (US1).
2. **STOP and VALIDATE**: run US1's Independent Test — a plan against a small
   suite version with both candidates and two repetitions, inspected for
   distinct attempts and zero Oracle leakage.
3. This is the smallest slice that produces real, immutable, auditable
   Attempts — but no score yet (that's US3).

### Incremental Delivery

1. US1 → attempts execute and are recorded, but nothing is scored yet.
2. + US2 → the shared endpoint is safe to run concurrently with feature 004's
   live challengers.
3. + US3 → the actual point of the feature: decision-grade scores per
   candidate, with the novel-finding panel.
4. + US4 → candidate versions are gated by a capability probe instead of
   trusted implicitly.

Each increment is independently testable per its own Independent Test in
spec.md, and none breaks a previously delivered story.
