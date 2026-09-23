# Tasks: Ground-Truth Review Corpus

## Phase 1: Corpus Contract

- [x] T001 Define public item and protected defect-label schemas.
- [x] T002 Define Base/Head, provenance, partition and Oracle separation policy.
- [x] T003 Define Gold correctness versus usefulness-rubric evaluation policy.

## Phase 2: Validator Foundation

- [x] T004 Add `src/benchmark/corpus/` package and `corpus validate` CLI.
- [x] T005 [P] Add item-manifest and protected-label schema validation tests.
- [x] T006 Add a runner-input builder that excludes Oracle paths/Git objects.
- [x] T007 [P] Add isolation, SHA/digest and scope-consistency tests.
- [x] T008 Add deterministic reproducer execution in a network-disabled sandbox.

## Phase 3: Pilot Fixtures and Evaluation

- [ ] T009 Create approved synthetic Python and TypeScript pilot fixture pairs.
- [ ] T010 Create protected Gold labels, reproducers and auditable curator records.
- [x] T011 Add finding mapping outcomes and usefulness-assessment persistence.
- [x] T012 [P] Test matched, duplicate, false-positive, insufficient-evidence and
  unmatched-Gold outcomes.
- [ ] T013 Render coverage and validation reports; show missing strata.

## Phase 4: v1 Release

- [ ] T014 Curate at least 24 reviewed items with five clean controls.
- [ ] T015 Run every Gold reproducer three times and record environment digests.
- [ ] T016 Perform holdout access/leakage review and release a content digest.
- [ ] T017 Add the released suite to an execution-plan integration test.

## Verification

- [ ] T018 `uv run benchmark corpus validate review-corpus/review-v1` exits 0.
- [x] T019 `uv run pytest tests/corpus && uv run pytest && uv run ruff check .` exits 0.
