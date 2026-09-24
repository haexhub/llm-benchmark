<!-- SPECKIT START -->
Current active feature: `specs/005-run-engine-adapters/`

- Spec: `specs/005-run-engine-adapters/spec.md`
- Plan: `specs/005-run-engine-adapters/plan.md`
- Research: `specs/005-run-engine-adapters/research.md`
- Data Model: `specs/005-run-engine-adapters/data-model.md`
- Contracts: `specs/005-run-engine-adapters/contracts/`
- Quickstart: `specs/005-run-engine-adapters/quickstart.md`

Read the plan first. `002-benchmark-platform` contains the shared constitution
and contracts. `003-review-ground-truth-corpus` is the released, curator-
approved 102-item Ground-Truth corpus this feature executes against.
`004-live-pr-shadow-review` is done; this feature reuses its
`SqliteResourceLeaseStore` unchanged (see 005's research.md R3) rather than
retrofitting it. The existing `001-pr-review-benchmark` remains the historical
PR-review spike and adapter-smoke-test feature; its outputs are not
decision-grade scores.
<!-- SPECKIT END -->
