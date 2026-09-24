# Run Engine Data Model

All catalogue identifiers are UUIDs; all timestamps are UTC ISO-8601, stored as
PostgreSQL `timestamptz`. Immutable fields are never updated after insert —
only new rows are added (constitution Principle I). This extends, and does not
redefine, `specs/002-benchmark-platform/data-model.md`.

## Catalogue (PostgreSQL)

| Table | Required fields | Notes |
|---|---|---|
| `execution_plan` | `id`, `suite_version_digest`, `candidate_version_ids[]`, `repetitions`, `resource_profile`, `score_policy_version`, `comparison_axis`, `idempotency_key`, `created_by`, `created_at` | `idempotency_key` = sha256 of the normalized request; a repeat request with the same key returns the existing row (FR-001). |
| `candidate_version` | `id`, `slug` (`gito`\|`pr-agent`), `tool_version`, `package_digest`, `model_endpoint_config_hash`, `capability_probe_status` (`pending`\|`passed`\|`failed`), `capability_probe_result`, `registered_at` | A failed or pending probe blocks use in a scored plan (FR-012). |
| `attempt` | `id`, `plan_id`, `item_id`, `candidate_version_id`, `sample_index`, `is_warmup` (always `false` in this feature), `retry_of_attempt_id` (nullable, self-FK), `capability_profile_id`, `comparison_axis`, `status`, `terminal_reason`, `manifest_digest`, `queued_at`, `leased_at`, `started_at`, `evaluated_at`, `finished_at` | Never overwritten (FR-003); a retry (FR-013a) is a new row with `retry_of_attempt_id` set. |
| `score` | `id`, `candidate_version_id`, `suite_version_digest`, `score_policy_version`, `metric_name`, `value`, `range_min`, `range_max`, `sample_count`, `computed_at` | One row per metric per candidate/suite/policy; `range_min`/`range_max` is the observed spread across repetitions (FR-010). |

## Execution (mixed: attempt row above + object storage)

| Entity | Required fields | Notes |
|---|---|---|
| `Artifact` | `id`, `attempt_id`, `kind` (`manifest`\|`raw_output`\|`normalized_findings`\|`evaluator_report`), `sha256`, `s3_uri`, `mime_type`, `size_bytes`, `created_at` | Content-addressed; `sha256` is the S3 object key prefix. Stored as a Postgres row referencing the S3-compatible object (FR-008). |
| `ResourceLease` | *(reused unchanged from feature 004)* | `SqliteResourceLeaseStore` row: `resource="local-94gb-gpu"`, `holder`, `token`, `expires_at`. Not duplicated into Postgres — see research.md R3. |

Attempt manifest content (the JSON persisted as the `manifest` Artifact) is
exactly `specs/002-benchmark-platform/contracts/attempt-manifest.schema.json`
— this feature does not redefine that schema, only populates it, with
`comparison_axis` always `"end_to_end_agent"` (research.md R11) and
`is_warmup` always `false`.

Attempt states (identical to `specs/002-benchmark-platform/data-model.md`):

```text
queued → leased → preparing → running → evaluating → succeeded|failed|timed_out|cancelled|invalid
```

A `failed`/`timed_out` Attempt whose `terminal_reason` is transient
(research.md R9) triggers automatic creation of a new `queued` Attempt with
`retry_of_attempt_id` set, up to the configured cap (default 3, FR-013a).
Non-transient terminal reasons never trigger a retry.

## Evaluation

| Table | Required fields | Notes |
|---|---|---|
| `evaluation` | `id`, `attempt_id`, `evaluator_version`, `finding_id`, `gold_label_id` (nullable), `outcome` (`matched`\|`duplicate`\|`false_positive`\|`insufficient_evidence`\|`unmatched_gold`), `evaluated_at` | One row per normalized finding per Attempt (FR-009); classification logic adapted from `matching/aggregator.py` (research.md, spec.md Assumptions). |
| `novel_finding_review` | `id`, `evaluation_id` (FK, `outcome='unmatched_gold'` only), `judge_model`, `verdict` (`plausible_novel_defect`\|`not_defect`\|`inconclusive`), `reasoning`, `prompt_hash`, `reviewed_at` | FR-009a; never joined into `score` computation — a separate panel only. |
| `gold_label_candidate` | `id`, `novel_finding_review_id` (FK, `verdict='plausible_novel_defect'` only), `item_id`, `location` (file/line range), `finding_summary`, `judge_reasoning`, `status` (`proposed`\|`promoted`\|`rejected`), `created_at`, `curator_reviewed_at` (nullable) | FR-009b. `status` only ever transitions away from `proposed` through 003's existing curator-approval pipeline (external to this feature's own write path) — this table is a read/export surface for that pipeline, not a place this engine writes `promoted`/`rejected` itself. |

`score` rows are computed by aggregating `evaluation` rows across every
`succeeded` Attempt (including every repetition) for a given
`candidate_version_id` × `suite_version_digest` × `score_policy_version` —
every Attempt is its own independent sample (research.md context, spec.md
FR-010); repetitions are never pre-reduced to one per-item verdict.

## Visibility

Same roles as `specs/002-benchmark-platform/data-model.md`: `runner` sees only
its fresh workspace's public fixture; `viewer` reads plan/attempt/score
metadata and redacted artifacts through the CLI; `curator` additionally reads
`gold_label_candidate` rows to drive 003's promotion pipeline. No new role is
introduced by this feature.
