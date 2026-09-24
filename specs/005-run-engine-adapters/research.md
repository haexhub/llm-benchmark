# Phase 0 Research: Run Engine and Adapters

## R1. Catalogue storage: hand-written SQL over an ORM/migration framework

**Decision**: PostgreSQL accessed via `psycopg[binary]>=3.2` directly, with
hand-written, numbered SQL migration files (`0001_...sql`, `0002_...sql`)
applied by a small runner in `runengine/db.py` — no SQLAlchemy, no Alembic.

**Rationale**: The existing codebase has zero ORM usage anywhere; even its one
existing durable store (`SqliteResourceLeaseStore`, feature 004) is plain
`sqlite3` + hand-written SQL. The 005 catalogue schema (six tables, no complex
relational queries beyond what spec.md's FRs require) doesn't need an ORM's
relationship-mapping or a full migration framework's branching/autogeneration
features. Matching the existing style (CLAUDE.md "Surgical Changes: match
existing style") keeps this the second, not the first, database-access
pattern in the repo, and keeps the schema auditable in a handful of plain
`.sql` files.

**Alternatives considered**: SQLAlchemy 2.0 + Alembic — rejected as the
heavier, more idiomatic-for-a-"platform" choice `specs/002-benchmark-platform/
plan.md` names, but unjustified for this schema's actual complexity, and would
introduce the repo's first ORM dependency for marginal benefit.

## R2. Artifact object storage: boto3 against an S3-compatible endpoint

**Decision**: `boto3>=1.34`'s S3 client, pointed at a `MINIO_*`-configured
endpoint (local docker-compose MinIO for dev; any real S3-compatible bucket in
production), following the existing `env()`/`require_env()` config pattern.

**Rationale**: `boto3` is the de facto standard client for S3-compatible
object storage (works unchanged against MinIO, Ceph, real AWS S3); no
justification exists for a MinIO-specific SDK given the artifact contract
(FR-008) only needs put/get/content-addressed-key operations.

**Alternatives considered**: `minio-py` — rejected; narrower ecosystem, no
benefit over `boto3` here since nothing MinIO-specific is used.

## R3. Resource lease: reuse `SqliteResourceLeaseStore` unchanged

**Decision**: `runengine/attempts.py` acquires its lease from the same
`SqliteResourceLeaseStore` instance (same `runs/run-engine.sqlite3` file, same
`local-94gb-gpu` resource key) that the existing `benchmark run` pipeline and
feature 004's `LiveShadowRunner` already use.

**Rationale**: Confirmed by reading `src/benchmark/live/resource_lease.py`,
`src/benchmark/live/runner.py` and `src/benchmark/pipeline.py`: this is
already a durable, cross-process, TTL-based, crash-recoverable exclusive
lease — exactly what constitution Principle IV and spec.md FR-004/FR-004a
require. Building a second (Postgres-backed) lease mechanism would duplicate
working code and reopen the exact serialization risk FR-004a exists to close
(two independent mechanisms that could theoretically disagree). This
supersedes the original FR-004a clarification answer, which assumed (based on
reading only `scheduler.py`) that a retrofit of feature 004 was needed; it
is not — see spec.md's Clarifications log for the correction.

**Alternatives considered**: A new Postgres-table-backed lease alongside the
catalogue — rejected; no functional gain, adds a second mechanism to keep in
sync with the first, and moves a latency-sensitive local lock onto a network
round-trip for no reason.

## R4. Novel-finding judge: extend the existing blind-judge module

**Decision**: Add `evaluate_novel_finding(finding, *, item_context) ->
NovelFindingVerdict` to `src/benchmark/matching/judge.py`, alongside the
existing `evaluate_pair`. Reuses the same blind-presentation discipline
(no tool/candidate identity in the prompt) and the same `AnthropicJudge`/
`OpenAICompatJudge`/`make_judge()` plumbing. New env var
`NOVEL_DEFECT_JUDGE_MODEL` (falls back to `JUDGE_LLM_MODEL` if unset) lets the
novel-finding judge be pinned to Claude Opus 5 independently of whatever model
the pair-matching judge uses.

**Rationale**: `judge.py` already implements exactly the blinding discipline
FR-009a requires (deterministic pseudo-random presentation, no candidate name
in the prompt, structured-JSON verdict parsing tolerant of fenced/prefixed
output). Building a second, parallel judge client would duplicate that
already-tested logic for no reason.

**Alternatives considered**: A standalone `novel_finding_judge.py` client —
rejected; would duplicate `_parse_verdict`, provider selection and blind
presentation instead of extending the existing `Protocol`.

## R5. Test infra: docker-compose + a new `db` pytest marker

**Decision**: Add `docker-compose.yml` at repo root with `postgres` and
`minio` services for local dev and integration tests. Add a new pytest marker
`db` ("tests requiring the local docker-compose Postgres/MinIO stack, opt-in,
not CI default"), distinct from the existing `live` marker. Update
`pyproject.toml`'s default `addopts` to `-m 'not live and not db'`.

**Rationale**: `live` already has an established, narrower meaning in this
repo ("hitting real external endpoints" — GitHub, Anthropic, OpenAI-compatible
LLM calls). Local docker-compose infrastructure is a different dependency
class (no network egress, no API cost, just "is docker-compose up"),
conflating the two would mislead a contributor reading `-m live` into
thinking it needs API keys when it actually just needs local containers.
Keeping the two orthogonal costs one extra line in `pyproject.toml` and
matches the existing "one marker per infra-dependency class" pattern.

**Alternatives considered**: Reusing `live` for both — rejected for the
semantic-drift reason above. A `testcontainers`-based ephemeral stack instead
of docker-compose — deferred; docker-compose matches what a human operator
would also run locally for manual testing/quickstart.md, and avoids adding a
test-only dependency for v1.

## R6. Fully synchronous implementation

**Decision**: `runengine/` is synchronous throughout (no `asyncio`, no async
`psycopg`/`boto3` clients), consistent with every existing module in
`src/benchmark/`.

**Rationale**: `grep`-confirmed zero `async def`/`asyncio` usage anywhere in
`src/benchmark/` today, despite `pytest-asyncio` being a declared (currently
unused) dev dependency likely added ahead of feature 007's future FastAPI
work. Introducing async here would be the first async code in the package for
a CLI/batch-execution feature that has no concurrency requirement beyond the
already-solved exclusive-lease serialization (R3). FastAPI/async, if needed,
belongs to feature 007 (the dashboard/control-plane API), which is out of
scope here.

**Alternatives considered**: Async psycopg/boto3 now, "for later" — rejected
per CLAUDE.md's Simplicity First ("no speculative flexibility that wasn't
requested").

## R7. CLI surface: new `runengine` Typer sub-app

**Decision**: Add `runengine_app = typer.Typer(...)`, mounted as `app.add_typer
(runengine_app, name="runengine")`, alongside the existing `corpus_app`/
`live_app` pattern. Commands: `runengine plan create`, `runengine plan list`,
`runengine attempt list/show`, `runengine score show`, `runengine
candidate register`.

**Rationale**: Matches the exact existing sub-app convention in `cli.py`
(`corpus_app`, `live_app`) rather than inventing a new top-level-command
style; satisfies FR-014 (CLI/API, no dashboard) with the smallest surface
that maps 1:1 onto spec.md's user stories (US1 plan/attempt, US3 score, US4
candidate registration).

**Alternatives considered**: Extending the existing bare `run`/`match`/
`report` top-level commands (the 001 legacy pipeline) — rejected; those are
explicitly documented (CLAUDE.md) as the historical, non-decision-grade spike
against `config/repos.yaml` PRs. Reusing their names/verbs for a
corpus-against-Oracle engine with different semantics (plans, repetitions,
Oracle scoring) would be confusing, not simplifying.

## R8. Candidate capability probe

**Decision**: Reuse the existing `check()` command's reachability logic
(`gito --help`/`pr-agent --help`, endpoint ping) as the basis for
`runengine candidate register`'s capability probe, but persist its result as
a structured `CandidateVersion.capability_probe_result` row instead of only
printing ✓/✗ to the console.

**Rationale**: `check()` (cli.py) already probes exactly the right things
(tool reachability, endpoint reachability); FR-012 just needs that result
persisted and gated on, not reinvented.

**Alternatives considered**: A wholly new probe mechanism — rejected as
duplicate logic for the same underlying checks.

## R9. Transient vs. non-transient failure classification (FR-013a)

**Decision**: An Attempt is retried automatically only when its terminal
reason is one of: subprocess timeout (`RunResult.timed_out`), non-zero exit
with empty stdout/stderr (connection-refused-class CLI failure), or an
explicit connection/timeout exception surfaced by the tool's HTTP client.
Any Attempt that produced output the adapter could not parse (schema drift,
FR-013) is never auto-retried — retrying it would just reproduce the same
result deterministically.

**Rationale**: Directly reuses the existing `RunResult`/`RunResult.ok`
vocabulary from `tools/base.py`, which already distinguishes "timed out" from
"produced output" — no new failure taxonomy needs inventing.

## R10. Score-policy instantiation

**Decision**: This feature ships one concrete, versioned score policy —
`review-v1-policy-1` — implementing exactly the metrics contracts/
score-policy.md already specifies (recall, precision, F1, false-positive
rate, duplicate rate, completion rate), stored as a small versioned YAML
alongside the migrations, referenced by its version string from every `Score`
row (never inlined/duplicated per-row).

**Rationale**: `specs/002-benchmark-platform/contracts/score-policy.md`
already defines the metric contract; 005 only needs to be its first concrete,
versioned implementation, not a new policy design.

## R11. `comparison_axis` for this feature's Attempts

**Decision**: Every Attempt this feature creates sets
`comparison_axis: "end_to_end_agent"` (never `model_under_harness`).

**Rationale**: gito and pr-agent are complete, self-contained review tools
(each bundling its own prompting/harness behavior around a configurable
model) — comparing them **is** comparing full end-to-end candidate
configurations, not holding one shared harness constant while swapping
models underneath it. `model_under_harness` would only become relevant if a
future candidate wrapped multiple models under one identical harness for a
controlled swap — out of scope here.
