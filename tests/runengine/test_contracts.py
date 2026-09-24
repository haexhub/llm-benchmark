"""Structural checks against specs/005-run-engine-adapters/contracts/*.schema.json.

No `jsonschema` dependency in this repo (matches tests/corpus's existing
convention of mirroring a *.schema.json contract with a small Pydantic model
rather than adding a generic schema-validation library).
"""
from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from benchmark.runengine.plan import PlanRequest, idempotency_key
from benchmark.runengine.scoring import MetricValue

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ExecutionPlanRequestContract(BaseModel):
    """Mirrors contracts/execution-plan-request.schema.json."""

    model_config = ConfigDict(extra="forbid", strict=True)

    suite_version_digest: Annotated[str, Field(pattern=_SHA256_PATTERN)]
    candidate_version_ids: Annotated[list[str], Field(min_length=1)]
    repetitions: Annotated[int, Field(ge=1)]
    retry_cap: Annotated[int, Field(ge=0)]
    resource_profile: Literal["local-94gb-gpu"]
    score_policy_version: Annotated[str, Field(min_length=1)]
    comparison_axis: Literal["end_to_end_agent"]
    idempotency_key: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _as_wire_request(request: PlanRequest) -> dict[str, object]:
    return {
        "suite_version_digest": f"sha256:{request.suite_version_digest}",
        "candidate_version_ids": [str(c) for c in request.candidate_version_ids],
        "repetitions": request.repetitions,
        "retry_cap": request.retry_cap,
        "resource_profile": "local-94gb-gpu",
        "score_policy_version": request.score_policy_version,
        "comparison_axis": "end_to_end_agent",
        "idempotency_key": idempotency_key(request),
    }


def test_plan_request_validates_against_the_contract() -> None:
    request = PlanRequest(
        suite_version_digest="a" * 64,
        candidate_version_ids=(uuid4(), uuid4()),
        repetitions=3,
        retry_cap=3,
        score_policy_version="review-v1-policy-1",
        created_by="haex",
    )

    ExecutionPlanRequestContract.model_validate(_as_wire_request(request))


def test_idempotency_key_is_a_bare_hex_digest() -> None:
    request = PlanRequest(
        suite_version_digest="a" * 64,
        candidate_version_ids=(uuid4(),),
        repetitions=1,
        retry_cap=0,
        score_policy_version="review-v1-policy-1",
        created_by="haex",
    )

    key = idempotency_key(request)

    assert re.fullmatch(r"[0-9a-f]{64}", key)


class _MetricValueContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | None
    sample_count: Annotated[int, Field(ge=0)]
    range_min: float | None = None
    range_max: float | None = None


class _ScoreReportMetricsContract(BaseModel):
    """Mirrors contracts/score-report.schema.json's `metrics` object."""

    model_config = ConfigDict(extra="forbid")

    recall: _MetricValueContract
    precision: _MetricValueContract
    f1: _MetricValueContract
    false_positive_rate: _MetricValueContract
    duplicate_rate: _MetricValueContract
    completion_rate: _MetricValueContract


class _NovelFindingsPanelContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plausible_novel_defect_count: Annotated[int, Field(ge=0)]
    not_defect_count: Annotated[int, Field(ge=0)]
    inconclusive_count: Annotated[int, Field(ge=0)]


class _ScoreReportContract(BaseModel):
    """Mirrors contracts/score-report.schema.json."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    candidate_version_id: str
    suite_version_digest: Annotated[str, Field(pattern=_SHA256_PATTERN)]
    score_policy_version: Annotated[str, Field(min_length=1)]
    metrics: _ScoreReportMetricsContract
    novel_findings: _NovelFindingsPanelContract


def _as_metric_dict(metric: MetricValue) -> dict[str, object]:
    return {
        "value": metric.value, "sample_count": metric.sample_count,
        "range_min": metric.range_min, "range_max": metric.range_max,
    }


def test_score_report_with_zero_successful_attempts_still_validates() -> None:
    zero = MetricValue(value=None, sample_count=0)
    completion = MetricValue(value=0.0, sample_count=1)

    report = _ScoreReportContract.model_validate(
        {
            "plan_id": str(uuid4()),
            "candidate_version_id": str(uuid4()),
            "suite_version_digest": f"sha256:{'a' * 64}",
            "score_policy_version": "review-v1-policy-1",
            "metrics": {
                "recall": _as_metric_dict(zero), "precision": _as_metric_dict(zero),
                "f1": _as_metric_dict(zero), "false_positive_rate": _as_metric_dict(zero),
                "duplicate_rate": _as_metric_dict(zero), "completion_rate": _as_metric_dict(completion),
            },
            "novel_findings": {
                "plausible_novel_defect_count": 0, "not_defect_count": 0, "inconclusive_count": 0,
            },
        }
    )

    assert report.metrics.recall.value is None


def test_novel_findings_panel_is_a_separate_field_never_merged_into_metrics() -> None:
    """The contract itself enforces this: `metrics` has no novel-finding fields
    (`additionalProperties: false`), so a caller physically cannot fold
    `plausible_novel_defect_count` into it without failing validation."""
    metric = MetricValue(value=1.0, sample_count=1, range_min=1.0, range_max=1.0)
    metrics_payload = {
        "recall": _as_metric_dict(metric), "precision": _as_metric_dict(metric),
        "f1": _as_metric_dict(metric), "false_positive_rate": _as_metric_dict(metric),
        "duplicate_rate": _as_metric_dict(metric), "completion_rate": _as_metric_dict(metric),
        "plausible_novel_defect_count": 3,  # attempting to smuggle it in
    }

    with pytest.raises(ValidationError):
        _ScoreReportMetricsContract.model_validate(metrics_payload)
