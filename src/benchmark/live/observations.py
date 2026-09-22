"""Filesystem-backed immutable state for the initial live PR shadow slice."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LivePRSnapshot(BaseModel):
    """The immutable public PR identity supplied to every live challenger."""

    model_config = ConfigDict(frozen=True)

    repository: str = Field(min_length=3)
    pr_number: int = Field(gt=0)
    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    diff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LivePRObservation(BaseModel):
    """One operational-only comparison record for one frozen PR revision."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot: LivePRSnapshot
    state: Literal[
        "queued", "running_challengers", "complete", "baseline_incomplete", "challenger_failed"
    ]
    created_at: datetime
    scoring_scope: Literal["operational_only"] = "operational_only"


class ObservationRecordResult(BaseModel):
    """Whether an event created a new observation or replayed an old one."""

    model_config = ConfigDict(frozen=True)

    observation: LivePRObservation
    created: bool


class LiveObservationStore:
    """Append-only local store; replaced by control-plane storage in a later slice."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def record(self, snapshot: LivePRSnapshot) -> ObservationRecordResult:
        """Create at most one queued observation for the exact immutable snapshot."""
        observation = LivePRObservation(
            id=_observation_id(snapshot),
            snapshot=snapshot,
            state="queued",
            created_at=datetime.now(UTC),
        )
        destination = self._path_for(snapshot)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("x") as output:
                output.write(observation.model_dump_json(indent=2) + "\n")
        except FileExistsError:
            return ObservationRecordResult(observation=self._load(destination), created=False)
        return ObservationRecordResult(observation=observation, created=True)

    def _path_for(self, snapshot: LivePRSnapshot) -> Path:
        repo_slug = snapshot.repository.replace("/", "__")
        revision = f"{snapshot.base_sha}__{snapshot.head_sha}"
        return self.root / repo_slug / str(snapshot.pr_number) / f"{revision}.json"

    @staticmethod
    def _load(source: Path) -> LivePRObservation:
        return LivePRObservation.model_validate_json(source.read_text())


def _observation_id(snapshot: LivePRSnapshot) -> str:
    identity = "\n".join(
        [snapshot.repository, str(snapshot.pr_number), snapshot.base_sha, snapshot.head_sha]
    )
    return hashlib.sha256(identity.encode()).hexdigest()
