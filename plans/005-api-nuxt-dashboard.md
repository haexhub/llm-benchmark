# Plan 005: Liefere Control Plane und Nuxt-Tailwind-Dashboard

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b764f88..HEAD -- src frontend apps specs docs plans`
> If Plans 002–004 have not supplied stable OpenAPI schemas, real attempts and
> score data, stop; do not invent a frontend-specific domain model.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED
- **Depends on**: `plans/002-ground-truth-review-corpus.md`, `plans/003-run-engine-resource-lease.md`, `plans/004-coding-task-harness.md`
- **Category**: direction
- **Planned at**: commit `b764f88`, 2026-09-22

## Why this matters

The user needs to create tasks, start runs and compare results without manually
reading JSON/Markdown files. The present CLI reports only PR-review snapshots;
there is no server, persistent query model or UI. Building a dashboard earlier
would duplicate unstable file formats and hide the difference between true
quality, historical CodeRabbit overlap, queue delay and failed attempts.

This plan puts a Nuxt 3 + Tailwind dashboard on the stable Python control-plane
API from Plan 003. It exposes experiments honestly: provenance and uncertainty
are first-class, and rankings never conceal reliability or resource contention.

## Current state

- No `package.json`, Nuxt app, API service or database exists at repository
  root; the project is currently a Python CLI.
- `src/benchmark/cli.py:191-273` has only fetch/run/match/report/all/review.
- Reports are generated from on-disk files in `pipeline.do_report`; summary
  values include historical CodeRabbit overlap and current runtime is zero.
- Plan 002 produces labelled review suites; Plan 003 produces API, Attempt,
  Artifact and Score records; Plan 004 produces coding tasks/attempts.

The dashboard must consume generated OpenAPI types and the control-plane's
authorization decisions. It may not read object storage or runner workspaces
directly.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Install frontend dependencies | `pnpm --dir frontend install --frozen-lockfile` | Exit 0 using committed lockfile |
| Generate typed client | `pnpm --dir frontend generate:api` | No diff beyond generated API client expected |
| Frontend checks | `pnpm --dir frontend lint && pnpm --dir frontend typecheck && pnpm --dir frontend test` | All exit 0 |
| API checks | `uv run pytest tests/api tests/control_plane` | API/query/authorization tests pass |
| E2E | `pnpm --dir frontend test:e2e` | Mocked API scenario passes |
| Full regression | `uv run pytest && uv run ruff check .` | Existing Python suite passes |

Use the repository's chosen Node package manager consistently. This plan names
`pnpm` because Nuxt/Tailwind integrations work well with it; if the team has a
standard different manager, document and use it consistently before scaffolding.

## Scope

**In scope**:

- New SpecKit feature `006-benchmark-control-plane-ui/**`
- `frontend/` Nuxt 3 + Tailwind application, generated API client and tests
- Completion of Plan-003 query/command endpoints and SSE status stream
- Role-aware task/suite/candidate registration and execution-plan creation
- Read-only artifact drill-down through signed/scoped API URLs

**Out of scope**:

- Putting LLM secrets, GPU endpoints or raw service credentials in browser code
- Direct browser access to PostgreSQL/object storage or runner hosts
- Editing ground-truth labels from a normal operator view
- A hidden proprietary weighted score or auto-starting unbounded GPU jobs

## Git workflow

- Branch: create through SpecKit as `006-benchmark-control-plane-ui`.
- Commit backend contract changes before their generated client/UI consumers.
- Do not expose the app publicly until authentication, CORS, artifact ACLs and
  audit logging have been tested in the deployment topology.

## Steps

### Step 1: Specify roles, workflows and API contracts

Create a SpecKit feature that defines four roles: viewer (read results),
operator (start/cancel permitted plans), curator (manage suites/tasks and hidden
truth through a protected workflow), and admin (candidate/resource configuration).
Resolve whether the initial deployment relies on your existing internal SSO or
a temporary authenticated reverse proxy; never ship an unauthenticated control
plane by default.

Finalize API contracts for catalogue lists/details, candidate/version register,
execution-plan preview/create, queue/cancel/retry, SSE attempt status, score
comparison, drill-down, and scoped artifact download. Every mutation requires
an idempotency key and audit actor/time; start-run requests show resource class,
estimated queue implications, suite version and candidates before confirmation.

**Verify**: OpenAPI tests cover all endpoints, all mutating endpoints have
authorization and idempotency tests, and client generation succeeds from the
published schema.

### Step 2: Establish the Nuxt application foundation

Scaffold `frontend/` with Nuxt 3, TypeScript, Tailwind, a committed lockfile,
server-safe runtime config and a generated OpenAPI client. Keep domain state in
small typed composables/stores derived from API types; do not reimplement score
calculation, queue scheduling or permission rules in the browser.

Provide application shell navigation: **Overview**, **Suites & Tasks**,
**Candidates**, **Run plans**, **Attempts**, **Compare**, and **Settings**
(admin-only). Design accessibly: keyboard navigation, semantic tables, color is
never the only severity/status indicator, loading/empty/error states and
localized German labels. Use Tailwind tokens/components consistently rather than
one-off inline style systems.

**Verify**: lint/typecheck/unit tests run on a mocked generated client; an
unauthorized route renders an access state without leaking protected metadata.

### Step 3: Build catalogue and safe run-start workflows

Implement list/detail pages for suites, suite versions, review fixtures and
coding tasks. Surface task language, size/difficulty, public spec and coverage;
never show hidden labels/tests/reference patches to ordinary users. Candidate
pages show tool/harness/model versions, capability-probe status, allowed
resource profiles and known config hash—not secret environment variables.

The run-plan wizard selects one suite version, candidate versions, repetitions,
budget policy and resource profile. It shows the matrix size, serial local GPU
constraint, predicted queue units and policy version. It submits an immutable
execution plan rather than immediate ad-hoc subprocesses; then displays queued,
leased, running and terminal Attempt counts via SSE with polling fallback.

**Verify**: E2E tests create a plan in a fake backend, show a one-slot queue,
reconnect SSE, cancel an eligible attempt and prove duplicate submission with
the same idempotency key does not create another plan.

### Step 4: Build honest comparison and drill-down views

Create the primary Compare view with filters for suite/version, modality,
language/stratum, candidate version, model, harness, resource profile and date.
Render a table plus Pareto scatter/matrix with quality, completion rate, median
end-to-end time, p95 time, queue wait and cost. Confidence intervals/sample
counts are shown with every aggregate; avoid a rank when cells are incomplete.

If an approved weighted policy is selected, display its version and weights next
to the rank and provide a toggle back to raw metrics. Review comparison must
separate ground-truth recall/precision/F1 from historical CodeRabbit overlap;
coding comparison must foreground hidden-test pass/score.

The Attempt detail shows frozen manifest/provenance, lifecycle/timings,
normalised findings or patch/test results, raw logs where authorized, evaluator
version and a visible invalid/failure reason. Artifact links are short-lived and
API-authorized; redact logs in the browser as a defense-in-depth step.

**Verify**: visual/E2E assertions cover a failed attempt, a partial score, a
legacy observation, a review result, a coding result and a filtered comparison;
tests assert no protected corpus artifact is returned for viewer/operator roles.

### Step 5: Operate, observe and document deployment

Add health endpoints, correlation IDs from UI request to Attempt, structured
frontend/API error reporting without secrets, audit trail views for mutations
and dashboard metrics for queue state. Provide a deployment guide for internal
reverse proxy, TLS, SSO/auth, narrow CORS origin list, database migrations,
object-storage lifecycle, backups and rollback. Add a local compose development
path with seeded fake data, not real endpoints/credentials.

Document how a curator creates a new task in the approved protected workflow,
how an operator schedules it, and how to interpret quality versus latency. Link
back to the associated SpecKit feature/score-policy/suite version from the UI.

**Verify**: fresh local setup using fake seed data passes E2E; API/browser
network inspection confirms no browser bundle contains token values or direct
storage/DB credentials.

## Test plan

- API: RBAC, idempotency, filtering/pagination, SSE authorization/reconnect,
  scoped artifact links and audit records.
- Frontend: generated-client type compatibility, empty/loading/error/status
  states, German accessible labels and role-gated navigation.
- E2E: task/candidate browse, execution-plan creation, serial queue status,
  cancel, results filter, raw versus weighted comparison, artifact ACLs.
- Security: CORS/auth configuration, secret scanning and attempted hidden-label
  access by viewer/operator roles.
- Full gates: frontend checks plus `uv run pytest && uv run ruff check .`.

## Done criteria

- [ ] Nuxt 3 + Tailwind dashboard consumes typed control-plane APIs only.
- [ ] Authorized users can inspect catalogues, create immutable run plans and
  observe/cancel attempts with an explicit one-GPU-slot queue.
- [ ] Compare view presents quality, reliability, latency, queue wait and cost
  with sample sizes/confidence and transparent score policy.
- [ ] Review ground truth, historical CodeRabbit overlap and coding test scores
  remain visibly distinct.
- [ ] Artifact/hidden-truth access is role-scoped and audited; no secret enters
  browser code or logs.
- [ ] All frontend/API/E2E/Python checks pass; `plans/README.md` is DONE.

## STOP conditions

- Stable Plan-003 APIs/attempt records or Plan-002/004 suites do not exist.
- Authentication/SSO ownership is unresolved for an internal network reachable
  by users other than a single developer.
- A requested screen requires exposing hidden labels, test inputs, reference
  patches or service secrets.
- Metrics are too sparse to justify ranking; show raw cells and a coverage gap
  instead of manufacturing a leaderboard.

## Maintenance notes

The UI is a control plane, not the source of benchmark truth. Keep all
scientific calculations server-side, version every visible aggregate and
regenerate API client types whenever contracts change. Future live progress
features must remain optional; a complete immutable Attempt record is the
fallback source of truth.
