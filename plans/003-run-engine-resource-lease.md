# Plan 003: Etabliere eine reproduzierbare Run-Engine mit exklusivem GPU-Lease

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat b764f88..HEAD -- pyproject.toml src/benchmark tests specs docs plans`
> If Plan 001's contracts or the present runner interfaces have drifted, stop
> and align this plan with the approved contract before changing code.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: `plans/001-benchmark-contracts-speckit.md`
- **Category**: direction
- **Planned at**: commit `b764f88`, 2026-09-22

## Why this matters

The current spike overwrites outputs under `runs/<repo>/<pr>/` and launches
gito and pr-agent concurrently. `src/benchmark/pipeline.py:73-111` therefore
contends on the same local Qwen endpoint despite the 94-GB capacity constraint.
It also supplies gito with a checkout but pr-agent only with a patch, which
makes the two reviewers see unequal context.

This plan introduces an immutable Attempt record, a small database-backed
control plane and a worker with an exclusive local-GPU lease. It preserves the
existing CLI as an adapter smoke test during migration, rather than attempting
a risky big-bang rewrite.

## Current state

- Python package: `pyproject.toml` uses Python 3.12+, Pydantic, Typer, httpx,
  Anthropic and OpenAI SDKs; it has no database or web API framework.
- `src/benchmark/models.py:9-109` is a narrow Pydantic model set; `Tool` is a
  fixed literal and has no attempt/provenance model.
- `pipeline.py:28-31` sets a 30-minute per-tool timeout and `do_run` uses a
  parallel `ThreadPoolExecutor`.
- `tools/gito.py:54-102` clones a PR worktree; `tools/pr_agent.py:78-91` runs a
  plain diff without a checkout. Both execute unpinned `uv tool run --from`.
- `reports/summary.py:144-160` stores runtime as `0.0`.
- Existing verification is `uv run pytest && uv run ruff check .` (99 selected
  tests today; one live test deselected).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Start dependencies | `docker compose up -d postgres minio` | Both internal services become healthy |
| Database migration | `uv run alembic upgrade head` | Schema is at head revision |
| API contract tests | `uv run pytest tests/api tests/control_plane` | All pass without a real LLM |
| Worker integration tests | `uv run pytest tests/worker -m 'not live'` | Fake runner proves lease/retry behavior |
| Existing regression | `uv run pytest && uv run ruff check .` | Existing tests remain green |
| Capability snapshot | `uv run benchmark adapters probe --candidate <id>` | Captures version, `--help`, output schema fingerprint |

The exact compose choice may be replaced by approved internal PostgreSQL and
object-storage endpoints, but production must use PostgreSQL and S3-compatible
artifact storage; SQLite is acceptable only for isolated test fixtures.

## Scope

**In scope**:

- New SpecKit feature `004-run-engine-and-adapters/**`
- Python control-plane/API and worker modules, Pydantic contracts and DB
  migrations
- Docker Compose only for local dev dependencies
- Refactoring gito/pr-agent into versioned review-adapter contracts
- Immutable artifact storage, telemetry, worker lifecycle and CLI migration

**Out of scope**:

- Nuxt dashboard pages (Plan 005)
- Curating labelled fixtures (Plan 002) and Coding agent adapters (Plan 004)
- Parallel local execution, automatic model swapping or multi-GPU scheduling
- Mutating external PRs, posting review comments or making production writes
  outside benchmark-owned storage

## Git workflow

- Branch: `004-run-engine-and-adapters` through SpecKit.
- Commit by vertical slice: schema/contracts, lease, worktree/artifacts, one
  adapter, migration/import, observability.
- Do not rewrite or delete legacy `runs/` artifacts until imports have been
  verified and a retention decision is documented.

## Steps

### Step 1: Specify the persisted control-plane contract

Write the feature spec and API schemas from Plan 001. Choose **Python +
FastAPI** for API/worker contracts because the existing normalizers and runner
code are Python. Choose **PostgreSQL** for catalogue, attempts, transitions and
leases; choose S3-compatible internal object storage for larger immutable
artefacts (worktree manifests, patches, stdout/stderr, raw outputs and test
reports).

Design API endpoints before UI: create/list suites and candidates, create an
execution plan, enqueue/cancel attempts, stream attempt state, retrieve
attempts/artifacts/scores, and only allow admin identities to view protected
curator artefacts. Document authentication and internal deployment boundaries.

**Verify**: OpenAPI generated from the FastAPI app validates against checked-in
schemas, and API tests assert authorization/visibility boundaries.

### Step 2: Implement immutable provenance and artifact storage

Create relational models/migrations for every Plan-001 noun. An Attempt must
reference exact suite digest, item revision, candidate version, harness/image
digest, normalized model ID, endpoint/resource class, prompt/config hash,
budgets, seed where supported, timestamps, terminal reason and evaluator
version. It must never be updated into a different candidate/configuration.

Write artifacts through a content-addressed store. Store a separate attempt
manifest first; then append artifact records with MIME type, digest, size,
retention class and access class. Redact environment values and credentials from
logs before storage. Record `queue_wait`, `prepare`, `runner`, `evaluation`
durations separately, plus token/cost fields when an adapter can report them.

**Verify**: an integration test enqueues two otherwise identical samples and
proves they receive different attempt IDs, manifests and artifact namespaces;
test that secret-like environment values never appear in persisted logs.

### Step 3: Implement resource profiles, lease and recovery

Create `ResourceProfile(local-94gb-gpu, capacity=1)` and enforce lease
acquisition transactionally in PostgreSQL. A worker atomically claims a queued
attempt only if it can create/renew that lease. Lease expiry/reaper logic must
return incomplete attempts to a safe retry state or mark them `invalid` after a
bounded retry policy; do not blindly run a possibly still-live process twice.

The scheduler must serialize every attempt that uses that profile, including
gito's internal calls. Exclude a recorded warm-up from final scoring. Preserve
queue order/audit fields and counterbalance candidate order in the plan creator;
the worker may not silently reorder scientific samples.

**Verify**: a concurrency test submits at least three local attempts and proves
max simultaneous active leases is one; kill a worker and prove the orphan lease
and process are handled without a duplicate scored result.

### Step 4: Make a deterministic attempt worktree and adapter contract

For every review attempt, create a fresh worktree from the same `base_sha` and
`head_sha`; mount no hidden corpus material. All runners receive this worktree,
the same policy/budget, a restricted network policy and a per-attempt temporary
home/config directory. Capture the input manifest and tree digest.

Define an adapter protocol such as `probe`, `prepare`, `execute`, `collect` and
`normalize`. Its output is a standard `RunnerResult` plus artifacts, never
directly a dashboard score. Pin candidate installation by exact version/image
digest and persist a capability probe (`--version`, redacted `--help`, result
schema fingerprint) when registered. Fail closed when a version's capability
contract drifts.

**Verify**: fake adapters run in identical worktrees and produce a comparable
input manifest; a deliberately changed CLI help/schema fails candidate
registration rather than silently altering results.

### Step 5: Migrate gito and PR-Agent fairly

Implement the two adapters against the versioned capability contract, not the
existing ad-hoc subprocess paths.

- Gito: use its approved local review mode and explicit worktree/path input;
  set its internal concurrency (`MAX_CONCURRENT_TASKS`) to one; isolate
  `.gito/config.toml` and environment configuration per attempt.
- PR-Agent: run in the same checkout rather than patch-only mode when its
  pinned version supports it; retain the exact diff input as an artifact; enable
  documented tool-error propagation so an internal review failure is not
  mistaken for a zero-finding success.

For both, pass the same local model endpoint/model identity, context/output
limits and any supported deterministic sampling options. Normalizers keep raw
severity but scores use Gold Truth severity. Preserve existing parser tests and
add adapter conformance fixtures from captured sanitized outputs.

**Verify**: adapter integration tests prove both tools see the same base/head
files, use one local lease, distinguish failed execution from zero findings and
record non-zero runner duration. Run a small labelled fixture manually before
opening batch scheduling.

### Step 6: Provide compatibility and operational interfaces

Retain `benchmark check` and legacy CLI commands as developer diagnostics.
Add a clear warning that the old parallel command is a legacy spike path; point
new work to `benchmark attempts enqueue` / worker commands. Provide a one-way
importer that records legacy runs as unscored `legacy_observation` attempts
with known missing provenance—never fabricate timing/tool-version fields.

Add structured logs, run/attempt correlation IDs, health/readiness endpoints,
metrics for queue length/lease/attempt status and a documented backup/retention
job. Ensure cancellation kills the whole process group as the current
`tools/base.py:34-61` already does.

**Verify**: command help, API docs and integration tests demonstrate enqueue,
progress, cancellation, legacy import and protected artifact access.

## Test plan

- Unit: state transition validation, immutable manifests, score-input
normalization, hash/redaction and schema/version compatibility.
- Database/API: transactional claim, lease renewal/expiry, authorization and
idempotency keys for enqueue/cancel requests.
- Worker: process-group cancellation, retry policy, object-storage write/read,
one-slot concurrency and same-worktree adapter parity.
- Adapter: pinned capability probes, parser fixtures, internal failure versus
zero results, tool telemetry collection.
- Regression: `uv run pytest && uv run ruff check .`.

## Done criteria

- [ ] Every scored result is an immutable Attempt with full provenance.
- [ ] PostgreSQL lease capacity prevents more than one local-inference attempt.
- [ ] Queue wait and actual runner time are independently reported.
- [ ] gito and PR-Agent are version-pinned, conformance-probed and given equal
  deterministic worktree context.
- [ ] Raw artifacts are content-addressed, access-scoped and secret-redacted.
- [ ] Legacy observations are separated from scored benchmark attempts.
- [ ] All new and existing tests pass; `plans/README.md` marks Plan 003 DONE.

## STOP conditions

- PostgreSQL/object storage cannot be hosted within the approved internal data
  boundary.
- Tool terms/licences prohibit the intended automated invocation.
- A runner needs private corpus material or host credentials beyond its
  narrowly-scoped service token.
- Lease recovery cannot reliably tell whether a previous process still runs;
  leave the attempt invalid and report rather than risking duplicate scoring.

## Maintenance notes

Candidate versions are scientific inputs. A package, CLI interface, image,
prompt template, tool config or model-server revision change creates a new
`CandidateVersion`; it never reuses historical results. Capacity may later grow
to several named profiles, but `local-94gb-gpu` must retain capacity one until
the hardware/operator explicitly changes the policy.
