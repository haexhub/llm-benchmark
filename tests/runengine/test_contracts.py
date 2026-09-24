"""Structural checks against specs/005-run-engine-adapters/contracts/*.schema.json.

No `jsonschema` dependency in this repo (matches tests/corpus's existing
convention of mirroring a *.schema.json contract with a small Pydantic model
rather than adding a generic schema-validation library).
"""
from __future__ import annotations

import re
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from benchmark.runengine.plan import PlanRequest, idempotency_key

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
