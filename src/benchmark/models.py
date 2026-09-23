from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Tool = Literal["coderabbit", "gito", "pr-agent"]
Severity = Literal["critical", "major", "minor", "nit", "info"]
Category = Literal["bug", "security", "perf", "style", "test", "doc", "other", "unknown"]
Classification = Literal["same", "different", "uncertain"]
ManualDecision = Literal["same", "different", "unclear"]

SEVERITY_SCORE: dict[Severity, int] = {
    "critical": 5,
    "major": 4,
    "minor": 3,
    "nit": 2,
    "info": 1,
}


class RepoConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pr_numbers: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def _positive_pr_numbers(self) -> RepoConfig:
        if any(n <= 0 for n in self.pr_numbers):
            raise ValueError("pr_numbers must all be > 0")
        return self

    @property
    def slug(self) -> str:
        return f"{self.owner}__{self.name}"


class LiveRepositoryIntegration(BaseModel):
    """Explicit opt-in and baseline policy for operational live PR shadowing."""

    model_config = ConfigDict(frozen=True)

    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    enabled: bool = False
    baseline_wait_minutes: int = Field(default=30, gt=0, le=1440)

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


class Finding(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tool: Tool
    file: str = Field(min_length=1)
    line_start: int = Field(ge=0)
    line_end: int = Field(ge=0)
    severity: Severity
    category: Category
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    suggestion: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _line_range(self) -> Finding:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be >= line_start")
        return self


class MatchCandidate(BaseModel):
    a_id: UUID
    b_id: UUID
    a_tool: Tool
    b_tool: Tool
    structural_overlap_lines: int = Field(ge=0)


class JudgeVerdict(BaseModel):
    same: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    judge_model: str
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Match(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    a_id: UUID
    b_id: UUID
    structural_overlap_lines: int = Field(ge=0)
    verdict: JudgeVerdict
    classification: Classification


class ManualReview(BaseModel):
    match_id: UUID
    decision: ManualDecision
    note: str | None = None
    reviewer: str = Field(min_length=1)
    ts: datetime


class PerToolStats(BaseModel):
    repo: str
    tool: Tool
    findings_raw: int = Field(ge=0)
    findings_after_dedup: int = Field(ge=0)
    overlap_with_cr: int = Field(ge=0)
    unique_to_tool: int = Field(ge=0)
    missed_from_cr: int = Field(ge=0)
    avg_severity_score: float = Field(ge=0.0)
    category_breakdown: dict[str, int] = Field(default_factory=dict)
    failed_pr_count: int = Field(ge=0)
    total_pr_count: int = Field(ge=0)
    runtime_seconds: float = Field(ge=0.0)
    manually_confirmed: int = Field(ge=0, default=0)
    manually_rejected: int = Field(ge=0, default=0)
