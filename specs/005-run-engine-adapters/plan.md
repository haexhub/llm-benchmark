# Implementation Plan: Run Engine and Adapters

**Branch**: `005-run-engine-adapters` | **Date**: 2026-09-24 | **Spec**: [spec.md](spec.md)

## Summary

Execute version-pinned gito/pr-agent candidates against every item of the
released `review-v1` Ground-Truth corpus (003) as immutable, PostgreSQL-backed
execution plans and attempts, evaluate their findings against the corpus's
protected Oracle labels, and report decision-grade recall/precision/F1 per
candidate — with a blinded-judge (Opus) panel for defects found beyond the
Gold set, never blended into the score. Reuses the existing durable
`SqliteResourceLeaseStore` for the exclusive `local-94gb-gpu` lease (already
shared by the legacy `benchmark run` pipeline and feature 004's live
challenger runner) rather than rebuilding it, and reuses the existing blind
frontier-judge module (`benchmark.matching.judge`) for the novel-finding
review. No dashboard; CLI/API only.

## Technical Context

**Language/Version**: Python 3.12+ (existing package; no new language).
**Primary Dependencies**: Existing `typer`, `pydantic`, `httpx`, `anthropic`,
`pyyaml`, `rich`. New: `psycopg[binary]>=3.2` (PostgreSQL driver, sync — the
rest of the codebase is fully synchronous, see research.md R6) and
`boto3>=1.34` (S3-compatible artifact object storage client).
**Storage**: PostgreSQL for the `ExecutionPlan`/`Attempt`/`CandidateVersion`/
`Evaluation`/`Score`/`NovelFindingReview`/`GoldLabelCandidate` catalogue
(hand-written SQL + numbered migrations, no ORM — see research.md R1); an
S3-compatible bucket (MinIO for local/dev, per research.md R2) for
content-addressed Artifacts; the existing `SqliteResourceLeaseStore`
(`runs/run-engine.sqlite3`) is reused unchanged for the exclusive resource
lease (see research.md R3).
**Testing**: pytest, existing `-m live` convention for tests hitting real
external endpoints (Anthropic judge, gito/pr-agent LLM calls); new `-m db`
marker for tests requiring the local docker-compose Postgres/MinIO stack
(research.md R5). Both stay opt-in, excluded from default `addopts`.
**Target Platform**: Internal Linux host running the existing worker/CLI
process plus a local docker-compose Postgres+MinIO pair for development.
**Project Type**: Single Python package (existing `src/benchmark/`), new
`runengine` subpackage plus a new top-level Typer sub-app; no frontend.
**Constraints**: One `local-94gb-gpu` capacity unit, never oversubscribed;
Oracle repository (`haexhub/llm-benchmark-review-oracle`) reachable only by
the post-run evaluator, never by a runner's workspace; no secret written to a
committed file, manifest, artifact or log (FR-016).
**Scale/Scope**: v1 targets the released 102-item `review-v1` corpus, 2
candidates (gito, pr-agent), default 3 repetitions per candidate/item cell —
612 attempts for a full run; the schema/engine is not item-count-bound beyond
that.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design (see below) — no violations either time.*

| Principle | Compliance |
|---|---|
| I. Reproducibility and Immutable Provenance (NON-NEGOTIABLE) | Every Attempt gets its own immutable manifest (reusing 002's `attempt-manifest.schema.json`); retries create new Attempt rows (FR-003, FR-013a); nothing is ever overwritten. |
| II. Independent Ground Truth (NON-NEGOTIABLE) | Decision-grade recall/precision/F1 (FR-010) come solely from the 003 Oracle's protected labels. The Opus judge (FR-009a) only labels `unmatched_gold` findings for a separate, non-scoring panel — it never becomes ranking truth, and any promotion into a real Gold label goes through 003's human curator pipeline (FR-009b), never this engine. |
| III. Equal, Isolated Candidate Conditions (NON-NEGOTIABLE) | FR-006/FR-007: every candidate in a plan gets the identical public Base/Head fixture, budget and capability policy in a fresh workspace; the Oracle is never mounted into a runner workspace (SC-004). |
| IV. Resource-Aware and Honest Measurement | FR-004/FR-004a: every Attempt against the shared local endpoint acquires the existing exclusive `local-94gb-gpu` lease; FR-005 records queue wait, setup, execution and evaluation time, tokens and cost separately. |
| V. Transparent Scores and Versioned Policy | FR-010/FR-011: quality, completion rate, latency and cost are reported separately, each tied to an explicit score-policy version; FR-010's per-repetition range surfaces sample uncertainty instead of hiding it behind one average. |
| VI. Secure Internal Operation | FR-016: no secret in a committed file/manifest/artifact/log; Postgres/MinIO credentials come from environment injection only (reusing the existing `.env`/`config.py` pattern), same as the existing `TOOL_LLM_*`/`JUDGE_LLM_*` variables. |

No constitution exception is required; no ADR needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-run-engine-adapters/
├── plan.md              # This file
├── research.md           # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output
│   ├── cli.md
│   ├── execution-plan-request.schema.json
│   ├── score-report.schema.json
│   └── gold-label-candidate.schema.json
└── tasks.md              # Phase 2 output (/speckit.tasks — not this command)
```

### Source Code (repository root)

```text
src/benchmark/
├── runengine/                    # NEW subpackage for this feature
│   ├── __init__.py
│   ├── db.py                     # psycopg connection helper + migration runner
│   ├── migrations/                # numbered .sql files (0001_..., 0002_...)
│   ├── plan.py                   # ExecutionPlan creation/idempotency
│   ├── attempts.py               # Attempt creation, workspace materialization, execution
│   ├── artifacts.py               # S3-compatible artifact put/get (boto3)
│   ├── evaluator.py               # Oracle-matching classification (adapts matching/aggregator.py)
│   ├── novel_finding.py           # FR-009a/FR-009b: judge triage + Gold-label-candidate export
│   ├── retry.py                   # FR-013a: transient-failure classification + bounded retry
│   └── scoring.py                 # FR-010/FR-011: per-candidate metric aggregation + spread
├── matching/
│   └── judge.py                   # EXTENDED: add evaluate_novel_finding() alongside evaluate_pair()
├── live/
│   └── resource_lease.py          # UNCHANGED — reused as-is by runengine/attempts.py
├── corpus/                        # UNCHANGED — runengine reads its public manifests/materializer
└── cli.py                         # EXTENDED: new `runengine_app` Typer sub-app

tests/
├── runengine/                     # NEW — unit tests (hermetic; fake DB/S3/judge)
└── integration/
    └── test_runengine_*.py        # NEW — `-m db` tests against real docker-compose Postgres/MinIO

docker-compose.yml                 # NEW — local Postgres + MinIO for dev/integration tests
```

**Structure Decision**: Single Python package, extended in place — matches
every prior feature (001-004) in this repo. A new `src/benchmark/runengine/`
subpackage holds this feature's own logic; it reads corpus items through the
existing `benchmark.corpus` package and reuses `benchmark.live.resource_lease`
and `benchmark.matching.judge` rather than duplicating them. No `frontend/`
directory is created (dashboard is feature 007, per spec.md's Assumptions).

## Complexity Tracking

No Constitution Check violations. This section is intentionally empty.
