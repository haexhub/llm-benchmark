"""Filesystem-backed immutable state for the initial live PR shadow slice."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from benchmark.models import Finding

if TYPE_CHECKING:
    from .scheduler import ChallengerResultRecordResult, LiveChallengerResult

_TERMINAL_STATES = frozenset({"complete", "baseline_incomplete", "challenger_failed"})

def _publish_once(destination: Path, content: str) -> bool:
    """Atomically publish a complete artifact; return False without changes if it exists."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(content)
    try:
        os.link(tmp_path, destination)
    except FileExistsError:
        return False
    finally:
        tmp_path.unlink(missing_ok=True)
    return True


def _publish_replacing(destination: Path, content: str) -> None:
    """Atomically replace an artifact; never expose a partially written file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    tmp_path.write_text(content)
    os.replace(tmp_path, destination)


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


class CodeRabbitSnapshot(BaseModel):
    """Normalized CodeRabbit output for one explicitly identified PR Head."""

    model_config = ConfigDict(frozen=True)

    head_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    findings: tuple[Finding, ...] = ()
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _contains_only_coderabbit_findings(self) -> CodeRabbitSnapshot:
        if any(finding.tool != "coderabbit" for finding in self.findings):
            raise ValueError("CodeRabbit findings must have tool='coderabbit'")
        return self


class CodeRabbitSnapshotRecordResult(BaseModel):
    """Whether a baseline capture was new or an idempotent replay."""

    model_config = ConfigDict(frozen=True)

    snapshot: CodeRabbitSnapshot
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
        if not _publish_once(destination, observation.model_dump_json(indent=2) + "\n"):
            return ObservationRecordResult(observation=self._load(destination), created=False)
        return ObservationRecordResult(observation=observation, created=True)

    def transition_state(
        self,
        snapshot: LivePRSnapshot,
        state: Literal[
            "running_challengers", "complete", "baseline_incomplete", "challenger_failed"
        ],
    ) -> LivePRObservation:
        """Update the observation's lifecycle state; the one field that isn't write-once.

        The revision identity (snapshot, id) never changes; only this field does,
        as the observation moves through queued -> running_challengers -> a
        terminal state.
        """
        destination = self._path_for(snapshot)
        current = self._load(destination)
        if current.state in _TERMINAL_STATES and state != current.state:
            raise ValueError(f"Cannot transition terminal observation from {current.state}")
        if current.state == state:
            return current
        updated = current.model_copy(update={"state": state})
        _publish_replacing(destination, updated.model_dump_json(indent=2) + "\n")
        return updated

    def record_with_diff(self, snapshot: LivePRSnapshot, diff: str) -> ObservationRecordResult:
        """Persist a diff only when it matches the snapshot's immutable digest."""
        actual_digest = hashlib.sha256(diff.encode()).hexdigest()
        if actual_digest != snapshot.diff_sha256:
            raise ValueError("Diff content does not match snapshot diff_sha256")
        result = self.record(snapshot)
        destination = self.diff_path(snapshot)
        if result.created:
            _publish_once(destination, diff)
        elif not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != actual_digest:
            raise ValueError("Existing observation has no matching immutable diff artifact")
        return result

    def diff_path(self, snapshot: LivePRSnapshot) -> Path:
        """Return the private, immutable patch artifact location for a snapshot."""
        return self._path_for(snapshot).with_suffix(".patch")

    def record_coderabbit_snapshot(
        self, observation: LivePRSnapshot, baseline: CodeRabbitSnapshot
    ) -> CodeRabbitSnapshotRecordResult:
        """Persist CodeRabbit output only when it names the observation's exact Head."""
        if baseline.head_sha != observation.head_sha:
            raise ValueError("CodeRabbit snapshot Head SHA does not match the observation")
        self.record(observation)
        destination = self.coderabbit_path(observation)
        if not _publish_once(destination, baseline.model_dump_json(indent=2) + "\n"):
            return CodeRabbitSnapshotRecordResult(
                snapshot=CodeRabbitSnapshot.model_validate_json(destination.read_text()),
                created=False,
            )
        return CodeRabbitSnapshotRecordResult(snapshot=baseline, created=True)

    def coderabbit_path(self, snapshot: LivePRSnapshot) -> Path:
        """Return the private, immutable CodeRabbit artifact location for a snapshot."""
        return self._path_for(snapshot).with_suffix(".coderabbit.json")

    def load_coderabbit_snapshot(self, observation: LivePRSnapshot) -> CodeRabbitSnapshot | None:
        """Load the captured CodeRabbit baseline for this immutable observation."""
        source = self.coderabbit_path(observation)
        if not source.is_file():
            return None
        return CodeRabbitSnapshot.model_validate_json(source.read_text())

    def record_challenger_result(
        self, observation: LivePRSnapshot, result: LiveChallengerResult
    ) -> ChallengerResultRecordResult:
        """Persist a challenger terminal result only for the exact immutable revision."""
        from .scheduler import ChallengerResultRecordResult, LiveChallengerResult

        attempt = result.attempt
        if attempt.base_sha != observation.base_sha or attempt.head_sha != observation.head_sha:
            raise ValueError("Challenger attempt SHA pair does not match the observation")
        if attempt.challenger not in {"gito", "pr-agent"}:
            raise ValueError("Unknown live challenger")
        self.record(observation)
        destination = self.challenger_path(observation, attempt.challenger)
        if not _publish_once(destination, result.model_dump_json(indent=2) + "\n"):
            return ChallengerResultRecordResult(
                result=LiveChallengerResult.model_validate_json(destination.read_text()),
                created=False,
            )
        return ChallengerResultRecordResult(result=result, created=True)

    def challenger_path(self, snapshot: LivePRSnapshot, challenger: str) -> Path:
        """Return the private, immutable artifact path for one recognized challenger."""
        if challenger not in {"gito", "pr-agent"}:
            raise ValueError("Unknown live challenger")
        return self._path_for(snapshot).with_suffix(f".{challenger}.json")

    def load_challenger_result(
        self, observation: LivePRSnapshot, challenger: str
    ) -> LiveChallengerResult | None:
        """Load one persisted terminal challenger result for this immutable observation."""
        from .scheduler import LiveChallengerResult

        source = self.challenger_path(observation, challenger)
        if not source.is_file():
            return None
        return LiveChallengerResult.model_validate_json(source.read_text())

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
