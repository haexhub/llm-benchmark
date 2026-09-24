-- Run Engine catalogue schema (specs/005-run-engine-adapters/data-model.md).
-- Applied once, in order, by db.py's migration runner (idempotent: guarded
-- by schema_migrations).

CREATE TABLE candidate_version (
    id UUID PRIMARY KEY,
    slug TEXT NOT NULL CHECK (slug IN ('gito', 'pr-agent')),
    tool_version TEXT NOT NULL,
    package_digest TEXT NOT NULL,
    model_endpoint_config_hash TEXT NOT NULL,
    capability_probe_status TEXT NOT NULL CHECK (capability_probe_status IN ('pending', 'passed', 'failed')),
    capability_probe_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE execution_plan (
    id UUID PRIMARY KEY,
    suite_version_digest TEXT NOT NULL,
    candidate_version_ids UUID[] NOT NULL,
    repetitions INTEGER NOT NULL CHECK (repetitions >= 1),
    retry_cap INTEGER NOT NULL DEFAULT 3 CHECK (retry_cap >= 0),
    resource_profile TEXT NOT NULL,
    score_policy_version TEXT NOT NULL,
    comparison_axis TEXT NOT NULL CHECK (comparison_axis = 'end_to_end_agent'),
    idempotency_key TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (created_by, idempotency_key)
);

CREATE TABLE attempt (
    id UUID PRIMARY KEY,
    plan_id UUID NOT NULL REFERENCES execution_plan (id),
    item_id TEXT NOT NULL,
    candidate_version_id UUID NOT NULL REFERENCES candidate_version (id),
    sample_index INTEGER NOT NULL CHECK (sample_index >= 0),
    is_warmup BOOLEAN NOT NULL DEFAULT false CHECK (is_warmup = false),
    retry_of_attempt_id UUID REFERENCES attempt (id),
    capability_profile_id TEXT NOT NULL,
    comparison_axis TEXT NOT NULL CHECK (comparison_axis = 'end_to_end_agent'),
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'leased', 'preparing', 'running', 'evaluating',
                   'succeeded', 'failed', 'timed_out', 'cancelled', 'invalid')
    ),
    terminal_reason TEXT,
    manifest_digest TEXT,
    oracle_label_count INTEGER CHECK (oracle_label_count >= 0),
    matched_gold_label_count INTEGER CHECK (matched_gold_label_count >= 0),
    missed_gold_label_count INTEGER CHECK (missed_gold_label_count >= 0),
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    leased_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    evaluated_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX attempt_plan_id_idx ON attempt (plan_id);
CREATE INDEX attempt_candidate_version_id_idx ON attempt (candidate_version_id);
CREATE INDEX attempt_retry_of_attempt_id_idx ON attempt (retry_of_attempt_id);

CREATE TABLE score (
    id UUID PRIMARY KEY,
    plan_id UUID NOT NULL REFERENCES execution_plan (id),
    candidate_version_id UUID NOT NULL REFERENCES candidate_version (id),
    suite_version_digest TEXT NOT NULL,
    score_policy_version TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value DOUBLE PRECISION,
    range_min DOUBLE PRECISION,
    range_max DOUBLE PRECISION,
    sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (plan_id, candidate_version_id, metric_name)
);

CREATE TABLE artifact (
    id UUID PRIMARY KEY,
    attempt_id UUID NOT NULL REFERENCES attempt (id),
    kind TEXT NOT NULL CHECK (kind IN ('manifest', 'raw_output', 'normalized_findings', 'evaluator_report')),
    sha256 TEXT NOT NULL,
    s3_uri TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX artifact_attempt_id_idx ON artifact (attempt_id);

CREATE TABLE evaluation (
    id UUID PRIMARY KEY,
    attempt_id UUID NOT NULL REFERENCES attempt (id),
    evaluator_version TEXT NOT NULL,
    finding_id UUID NOT NULL,
    gold_label_id TEXT,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('matched', 'duplicate', 'false_positive', 'insufficient_evidence', 'unmatched_gold')
    ),
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX evaluation_attempt_id_idx ON evaluation (attempt_id);

CREATE TABLE novel_finding_review (
    id UUID PRIMARY KEY,
    evaluation_id UUID NOT NULL REFERENCES evaluation (id),
    judge_model TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('plausible_novel_defect', 'not_defect', 'inconclusive')),
    reasoning TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE gold_label_candidate (
    id UUID PRIMARY KEY,
    novel_finding_review_id UUID NOT NULL REFERENCES novel_finding_review (id),
    item_id TEXT NOT NULL,
    location_file TEXT NOT NULL,
    location_line_start INTEGER NOT NULL,
    location_line_end INTEGER NOT NULL,
    finding_summary TEXT NOT NULL,
    judge_reasoning TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'promoted', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    curator_reviewed_at TIMESTAMPTZ
);
