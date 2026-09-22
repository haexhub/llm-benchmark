# Tasks: Benchmark Platform Foundation

**Input**: [spec.md](spec.md), [plan.md](plan.md), [data-model.md](data-model.md)

## Phase 1: Platform Contract

- [x] T001 Ratify `.specify/memory/constitution.md` with reproducibility,
  Ground Truth, isolation, resource and score-policy principles.
- [x] T002 Create the `002-benchmark-platform` specification and requirements
  checklist.
- [x] T003 Define common catalogue, execution, evaluation and visibility nouns
  in `data-model.md`.
- [x] T004 Define attempt-manifest and score-policy contracts.
- [x] T005 Record staged architecture and migration boundaries in `plan.md`.

**Checkpoint**: All later features share unambiguous Attempt, Artifact, Score,
SuiteVersion and ResourceLease terms.

## Phase 2: Review Ground Truth (next feature)

- [ ] T006 Create `003-review-ground-truth-corpus` through SpecKit.
- [ ] T007 Specify fixture visibility, label/reproducer validation and
  two-reviewer adjudication.
- [ ] T008 Build the small stratified v1 corpus including clean controls.

## Phase 3: Run Engine (next feature)

- [ ] T009 Create `004-run-engine-and-adapters` through SpecKit.
- [ ] T010 Implement immutable PostgreSQL attempts/artifacts and tests.
- [ ] T011 Implement `local-94gb-gpu` transactional lease and recovery tests.
- [ ] T012 Introduce deterministic worktrees and version-pinned adapter probes.
- [ ] T013 Migrate Gito/PR-Agent onto fair adapters; import legacy runs only as
  incomplete observations.

## Phase 4: Coding Harness (next feature)

- [ ] T014 Create `005-live-pr-shadow-review` through SpecKit.
- [ ] T015 Define repository opt-in, GitHub events, CodeRabbit completion and
  head-SHA snapshot policy.
- [ ] T016 Implement serial Gito/PR-Agent shadow attempts and private
  comparison rendering.

## Phase 5: Coding Harness (next feature)

- [ ] T017 Create `006-coding-task-harness` through SpecKit.
- [ ] T018 Define isolated task packets, protected hidden tests and evaluator.
- [ ] T019 Add direct-model, Hermes and OpenCode adapter conformance tests.
- [ ] T020 Run balanced three-sample pilot under one GPU lease.

## Phase 6: Control Plane UI (next feature)

- [ ] T021 Create `007-benchmark-control-plane-ui` through SpecKit.
- [ ] T022 Provide authenticated typed API and audit/idempotency checks.
- [ ] T023 Build Nuxt/Tailwind catalogue, plan, status, comparison and drilldown views.
- [ ] T024 Add frontend/API/E2E access-control and hidden-artifact tests.

## Verification

- [x] T025 Run `uv run pytest && uv run ruff check .` for the unchanged Python
  spike baseline.
- [ ] T026 Before each later slice, run the exact contract and regression gates
  specified in its feature plan.
