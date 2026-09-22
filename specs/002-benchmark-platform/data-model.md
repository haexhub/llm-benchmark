# Platform Data Model

All identifiers are UUIDs; all timestamps are UTC ISO-8601. Immutable fields
cannot be changed after creation. The later implementation uses PostgreSQL for
catalogue/state and content-addressed internal object storage for artifacts.

## Catalogue

| Entity | Required fields | Notes |
|---|---|---|
| `BenchmarkSuite` | `id`, `slug`, `modality` (`review`/`coding`), owner | Logical suite family. |
| `SuiteVersion` | `id`, `suite_id`, partition (`development`/`calibration`/`holdout`), semantic version, `content_digest`, evaluator version, visibility policy, status | Released versions are immutable. |
| `BenchmarkItem` | `id`, `suite_version_id`, slug, public manifest digest, source/base/head revision, language, size/difficulty buckets, provenance, contamination status | Hidden Oracle references are curator-only. |
| `Candidate` | `id`, slug, kind (`review_tool`/`coding_agent`/`direct_model`) | A user-facing candidate family. |
| `CandidateVersion` | `id`, `candidate_id`, tool/harness version, image/package digest, model ID, config/prompt hash, capability-probe artifact | Any runtime-affecting change creates a new version. |
| `CapabilityProfile` | `id`, version, filesystem/shell/git rights, network class, MCP list+hashes, skills bundle hash, memory mode, sub-agent policy | A first-class comparison factor, never implied by a tool name. |
| `RepositoryIntegration` | `id`, repository identity, enabled state, GitHub event policy, baseline provider identity, baseline wait, retention and publication policy | Explicit opt-in for live PR shadow review. |
| `ScorePolicy` | `id`, version, metric definitions, optional disclosed weights | Scores never cross policy versions silently. |

## Execution

| Entity | Required fields | Notes |
|---|---|---|
| `ExecutionPlan` | `id`, creator/audit actor, suite version, candidate versions, repetitions, safety ceilings, score-policy, comparison axis, ordering seed | Frozen matrix; idempotency key is unique per actor/request. |
| `Attempt` | `id`, plan/item/candidate/capability-profile references, sample index, `is_warmup`, manifest digest, status, terminal reason, timestamps | Immutable scientific sample. |
| `ResourceProfile` | `id`, slug, capacity, policy version | Initial `local-94gb-gpu` capacity is 1. |
| `ResourceLease` | `id`, attempt/resource references, acquired/renewed/expires timestamps, holder | Only one active lease per capacity unit. |
| `Artifact` | `id`, attempt reference, kind, SHA-256, URI, MIME type, size, retention/access class | Manifest, worktree digest, patch, logs, raw output, test report and evaluation are separate artifacts. |
| `LivePRObservation` | `id`, RepositoryIntegration, PR number, base SHA, head SHA, baseline snapshot artifact, challenger attempt IDs, state | Operational comparison; never a Ground-Truth score. |

Attempt states are `queued → leased → preparing → running → evaluating →
succeeded|failed|timed_out|cancelled|invalid`. Recovery may move an expired lease
to `queued` only when no process can remain active; otherwise it ends `invalid`.

Live observation states are `baseline_waiting`, `running_challengers`, `complete`,
`baseline_incomplete`, `challenger_failed` and `superseded`. A unique tuple of
`(repository integration, PR number, head SHA)` prevents results from different
PR revisions being combined.

## Evaluation

| Entity | Required fields | Notes |
|---|---|---|
| `DefectLabel` | opaque ID, hidden item reference, category, gold severity, scope, reproducer, provenance, adjudication state | Review-only protected Ground Truth. |
| `UsefulnessAssessment` | finding/evaluation reference, correctness source, actionability, severity calibration, redundancy, attention cost, blind judge/human rubric version | Review finding utility; not a self-reported candidate score. |
| `Evaluation` | attempt/evaluator version, status, evidence artifact, metrics, completion state | Immutable output of an evaluator run. |
| `Score` | evaluation/policy references, metric name/value, sample count, confidence interval | Raw metrics and weighted rank remain separate. |

Review evaluation maps normalized findings to `matched`, `duplicate`,
`false_positive`, `insufficient_evidence` or `unmatched_gold`; humans adjudicate
all gold cases and a blinded finding sample. Coding evaluation records public and
hidden test outcomes; hidden acceptance/regression checks determine primary
quality.

Every comparison states `comparison_axis`: `model_under_harness` holds harness
and CapabilityProfile constant while varying model/runtime, whereas
`end_to_end_agent` intentionally compares full candidate configurations. Actual
time, queue wait, tokens, tool calls and cost are observations; safety ceilings
only terminate runaway attempts.

## Visibility

`runner` sees public manifests and its fresh worktree only. `viewer` sees public
attempt/score metadata and authorized redacted artifacts. `operator` may create
plans and cancel eligible work. `curator` additionally manages hidden Oracle
material. `admin` manages candidates/resources. Secrets are never an entity or
artifact.
