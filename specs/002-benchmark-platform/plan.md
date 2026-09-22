# Implementation Plan: Benchmark Platform Foundation

**Branch**: `002-benchmark-platform` | **Date**: 2026-09-22 | **Spec**: [spec.md](spec.md)

## Summary

Evolve the tested Python PR-review spike into a control plane for immutable
benchmark attempts. First define contracts, Ground Truth and fair scheduling;
then deliver a review corpus, PostgreSQL-backed worker/API, coding harness and
Nuxt dashboard in separate SpecKit features. Existing CLI flows remain adapter
diagnostics and legacy observations during migration.

## Technical Context

**Language/Version**: Python 3.12+ backend/workers; TypeScript/Nuxt 3 frontend
in later feature.  
**Primary Dependencies**: Existing Pydantic/Typer/httpx; FastAPI, SQLAlchemy and
Alembic for the control plane; Nuxt 3 + Tailwind + generated OpenAPI client.  
**Storage**: PostgreSQL for catalogue/state/leases; S3-compatible internal object
storage for immutable artifacts.  
**Testing**: pytest/pytest-asyncio/Ruff; later API contract tests and Nuxt
type/lint/unit/E2E tests.  
**Target Platform**: Internal Linux workers, isolated containers/worktrees, web
dashboard.  
**Project Type**: Python package evolving into worker/API plus `frontend/`.  
**Constraints**: `local-94gb-gpu` capacity 1; no hidden oracle/secret leakage;
external endpoints only in opt-in live tests.  
**Scale/Scope**: v1 starts with small Python/TypeScript review and coding suites;
three scored samples per candidate/item cell.

## Constitution Check

| Principle | Foundation compliance |
|---|---|
| Immutable provenance | Attempt/Artifact/manifest contract is defined before persistence. |
| Independent Ground Truth | Review labels and coding hidden tests are mandatory evaluator inputs. |
| Equal isolation | Public/hidden visibility and fresh-workspace rules are specified. |
| Resource honesty | One-slot lease and timing boundaries are functional requirements. |
| Transparent scores | Raw metrics, uncertainty and versioned policy are required. |
| Secure operation | Secrets and protected artifacts are scoped out of runners and browser. |

No constitution exception is required.

## Project Structure

```text
specs/002-benchmark-platform/       # foundation documents and contracts
docs/adr/                           # durable platform decisions
src/benchmark/                      # existing CLI; future api/control_plane/worker/adapters
tests/                              # existing unit/integration; future contract/api/worker/corpus
review-corpus/                      # Plan 002, versioned review fixtures (or approved internal repo)
coding-corpus/                      # Plan 004, versioned coding tasks
frontend/                           # Plan 005, Nuxt 3 + Tailwind
plans/                              # execution handoff plans
```

## Delivery Slices

1. **003-review-ground-truth-corpus**: validated versioned seeded PR corpus;
   defect labels/reproducers and human adjudication.
2. **004-run-engine-and-adapters**: PostgreSQL attempts, artifact storage,
   exclusive lease, fair worktrees and version-pinned Gito/PR-Agent adapters.
3. **005-live-pr-shadow-review**: GitHub event intake, immutable CodeRabbit
   baseline snapshots, serial gito/PR-Agent challenger attempts and private
   three-way comparisons for opted-in repositories.
4. **006-coding-task-harness**: isolated task packets, hidden tests, direct
   model/Hermes/OpenCode adapters and evaluator.
5. **007-benchmark-control-plane-ui**: authenticated FastAPI endpoints and
   Nuxt/Tailwind operations/comparison dashboard.

Each slice must pass its own Constitution Check and update this plan only when a
contract compatibility change is approved.
