"""Attempt creation, workspace materialization and candidate execution."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import psycopg
import yaml

from benchmark.corpus import RunnerInput, materialize_review_input
from benchmark.corpus.oracle import ProtectedDefectLabel, validate_protected_defect_label
from benchmark.live import ResourceLease, SqliteResourceLeaseStore
from benchmark.matching.judge import NovelFindingVerdict, make_novel_finding_judge
from benchmark.models import Finding
from benchmark.runengine.artifacts import ArtifactStore
from benchmark.runengine.evaluator import (
    EVALUATOR_VERSION,
    AttemptEvaluation,
    evaluate_attempt_findings,
)
from benchmark.runengine.novel_finding import (
    propose_gold_label_candidate,
    record_novel_finding_review,
)
from benchmark.runengine.plan import ExecutionPlan
from benchmark.runengine.retry import classify_failure, should_retry
from benchmark.tools.base import RunResult
from benchmark.tools.gito import GITO_REPORT_FILENAME, load_gito_findings, run_gito_on_bundle
from benchmark.tools.pr_agent import load_pragent_findings, run_pragent_on_diff

log = logging.getLogger("benchmark.runengine")

RESOURCE_NAME = "local-94gb-gpu"
LEASE_TTL_SECONDS = 3600
# Matches pipeline.py's TOOL_TIMEOUT_SECONDS; not imported from there to avoid
# pulling in benchmark.reports, which exists in the primary checkout but was
# never actually committed to git (breaks on any fresh clone/worktree).
DEFAULT_TIMEOUT_SECONDS = 1800
LEASE_HEARTBEAT_INTERVAL_SECONDS = LEASE_TTL_SECONDS / 3

CAPABILITY_PROFILE_ID = uuid5(NAMESPACE_URL, "runengine-v1-capability-profile")

# attempt-manifest.schema.json requires item_id to be a UUID, but corpus items
# use human-readable slugs (e.g. "python-cache-miss"). Derive a stable UUID
# from the slug for the manifest only; the `attempt` table keeps the real slug.
def item_uuid(item_id: str) -> UUID:
    """Derive a stable manifest UUID from a human-readable corpus item ID."""
    return uuid5(NAMESPACE_URL, f"review-corpus-item:{item_id}")


@dataclass(frozen=True)
class Attempt:
    id: UUID
    plan_id: UUID
    item_id: str
    candidate_version_id: UUID
    sample_index: int
    retry_of_attempt_id: UUID | None
    status: str


def create_attempts(
    conn: psycopg.Connection,
    store: ArtifactStore,
    plan: ExecutionPlan,
    item_ids: list[str],
    *,
    model: str,
    config_hash_by_candidate: dict[UUID, str],
) -> list[Attempt]:
    """Create one Attempt (+ manifest Artifact) per candidate x item x repetition."""
    attempts: list[Attempt] = []
    with conn.cursor() as cur:
        for item_id in item_ids:
            for candidate_version_id in plan.candidate_version_ids:
                for sample_index in range(plan.repetitions):
                    attempt_id = uuid4()
                    created_at = datetime.now(UTC)
                    manifest = _build_manifest(
                        attempt_id=attempt_id,
                        suite_version_digest=plan.suite_version_digest,
                        item_id=item_id,
                        candidate_version_id=candidate_version_id,
                        model=model,
                        config_hash=config_hash_by_candidate[candidate_version_id],
                        score_policy_version=plan.score_policy_version,
                        resource_profile=plan.resource_profile,
                        created_at=created_at,
                    )
                    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
                    manifest_digest = sha256(manifest_bytes).hexdigest()
                    cur.execute(
                        """
                        INSERT INTO attempt
                            (id, plan_id, item_id, candidate_version_id, sample_index,
                             capability_profile_id, comparison_axis, status, manifest_digest,
                             queued_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued', %s, %s)
                        """,
                        (
                            attempt_id, plan.id, item_id, candidate_version_id, sample_index,
                            str(CAPABILITY_PROFILE_ID), plan.comparison_axis, manifest_digest,
                            created_at,
                        ),
                    )
                    stored = store.put(manifest_bytes, content_type="application/json")
                    cur.execute(
                        """
                        INSERT INTO artifact (id, attempt_id, kind, sha256, s3_uri, mime_type, size_bytes)
                        VALUES (%s, %s, 'manifest', %s, %s, 'application/json', %s)
                        """,
                        (uuid4(), attempt_id, stored.sha256, stored.s3_uri, stored.size_bytes),
                    )
                    attempts.append(
                        Attempt(
                            id=attempt_id, plan_id=plan.id, item_id=item_id,
                            candidate_version_id=candidate_version_id, sample_index=sample_index,
                            retry_of_attempt_id=None, status="queued",
                        )
                    )
    conn.commit()
    return attempts


def _build_manifest(
    *,
    attempt_id: UUID,
    suite_version_digest: str,
    item_id: str,
    candidate_version_id: UUID,
    model: str,
    config_hash: str,
    score_policy_version: str,
    resource_profile: str,
    created_at: datetime,
) -> dict[str, object]:
    """Build the immutable attempt manifest required by the benchmark contract."""
    return {
        "attempt_id": str(attempt_id),
        "suite_version_digest": f"sha256:{suite_version_digest}",
        "item_id": str(item_uuid(item_id)),
        "candidate_version_id": str(candidate_version_id),
        "model": model,
        "config_hash": f"sha256:{config_hash}",
        "capability_profile_id": str(CAPABILITY_PROFILE_ID),
        "comparison_axis": "end_to_end_agent",
        "evaluator_version": EVALUATOR_VERSION,
        "score_policy_version": score_policy_version,
        "resource_profile": resource_profile,
        "budget": {"wall_seconds": DEFAULT_TIMEOUT_SECONDS},
        "is_warmup": False,
        "created_at": created_at.isoformat(),
    }


def materialize_workspace(corpus_root: Path, item_id: str, workspace_root: Path) -> RunnerInput:
    """Materialize the item's public fixture only; never touches Oracle material."""
    return materialize_review_input(corpus_root, item_id, workspace_root / "input")


@dataclass(frozen=True)
class ToolExecutionOutcome:
    """Everything needed to persist an Attempt's result and, on failure, classify a retry."""

    ok: bool
    timed_out: bool
    returncode: int
    stdout: str
    stderr: str
    raw_output: bytes = b""
    findings: tuple[Finding, ...] = ()
    schema_drift: bool = False
    schema_drift_detail: str = ""


class CandidateExecutor(Protocol):
    def __call__(
        self, *, candidate_slug: str, corpus_root: Path, item_id: str,
        runner_input: RunnerInput, work_dir: Path, timeout: int,
        tool_version: str | None = None, cancel_event: threading.Event | None = None,
    ) -> ToolExecutionOutcome: ...


def default_candidate_executor(
    *, candidate_slug: str, corpus_root: Path, item_id: str,
    runner_input: RunnerInput, work_dir: Path, timeout: int,
    tool_version: str | None = None, cancel_event: threading.Event | None = None,
) -> ToolExecutionOutcome:
    """Run the real gito or pr-agent CLI against a materialized corpus item."""
    if candidate_slug == "pr-agent":
        out_file = work_dir / "pr-agent.json"
        result = run_pragent_on_diff(
            runner_input.diff_file, out_file, timeout=timeout,
            cancel_event=cancel_event, tool_version=tool_version,
        )
        return _finish_execution(result, out_file, load_pragent_findings)
    if candidate_slug == "gito":
        manifest = yaml.safe_load(runner_input.manifest_file.read_text())
        bundle = corpus_root / "items" / item_id / "repo.bundle"
        clone_dir = work_dir / "gito-clone"
        out_dir = work_dir / "gito-out"
        result = run_gito_on_bundle(
            bundle, manifest["base_sha"], manifest["head_sha"], clone_dir, out_dir,
            timeout=timeout, cancel_event=cancel_event, tool_version=tool_version,
        )
        return _finish_execution(result, out_dir / GITO_REPORT_FILENAME, load_gito_findings)
    raise ValueError(f"Unknown candidate slug: {candidate_slug!r}")


def _renew_lease_until_stopped(
    lease: ResourceLease,
    stop_event: threading.Event,
    lease_lost_event: threading.Event,
) -> None:
    """Renew a lease independently while a blocking candidate process runs."""
    while not stop_event.wait(LEASE_HEARTBEAT_INTERVAL_SECONDS):
        try:
            renewed = lease.renew(ttl_seconds=LEASE_TTL_SECONDS)
        except (OSError, sqlite3.Error):
            log.exception("lease heartbeat failed for %s", lease.resource)
            renewed = False
        if not renewed:
            lease_lost_event.set()
            log.error("lost %s lease during candidate execution", RESOURCE_NAME)
            return


def _finish_execution(
    result: RunResult, output_path: Path, loader: Callable[[Path], list[Finding]]
) -> ToolExecutionOutcome:
    """Convert tool output into findings or a schema-drift failure."""
    if not result.ok:
        return ToolExecutionOutcome(
            ok=False, timed_out=result.timed_out, returncode=result.returncode,
            stdout=result.stdout, stderr=result.stderr,
        )
    try:
        findings = tuple(loader(output_path))
    except (OSError, ValueError, KeyError) as error:
        return ToolExecutionOutcome(
            ok=False, timed_out=False, returncode=result.returncode,
            stdout=result.stdout, stderr=result.stderr,
            schema_drift=True, schema_drift_detail=str(error),
        )
    raw_output = output_path.read_bytes() if output_path.exists() else b""
    return ToolExecutionOutcome(
        ok=True, timed_out=False, returncode=result.returncode,
        stdout=result.stdout, stderr=result.stderr,
        raw_output=raw_output, findings=findings,
    )


def run_attempt(
    conn: psycopg.Connection,
    store: ArtifactStore,
    *,
    attempt_id: UUID,
    corpus_root: Path,
    item_id: str,
    candidate_slug: str,
    model: str,
    config_hash: str,
    workspace_root: Path,
    runs_dir: Path,
    tool_version: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    executor: CandidateExecutor = default_candidate_executor,
    lease_store: SqliteResourceLeaseStore | None = None,
    oracle_root: Path | None = None,
    novel_finding_judge: NovelFindingJudge | None = None,
) -> ToolExecutionOutcome | None:
    """Execute one queued Attempt under the shared exclusive lease.

    Returns None (and leaves the Attempt `queued`) if the lease is held by
    another worker — callers should try again later, matching the existing
    `pipeline.py`/`live/runner.py` convention rather than blocking.

    `lease_store` is injectable (defaults to the real `runs_dir`-backed store)
    so a test can simulate a lost/expired lease deterministically, without a
    real sleep — see test_lease_recovery.py.
    """
    if timeout >= LEASE_TTL_SECONDS:
        raise ValueError(f"timeout ({timeout}s) must be below LEASE_TTL_SECONDS ({LEASE_TTL_SECONDS}s)")
    worker_id = f"runengine-{attempt_id}"
    if lease_store is None:
        lease_store = SqliteResourceLeaseStore(runs_dir / "run-engine.sqlite3")
    lease = lease_store.acquire(RESOURCE_NAME, worker_id, ttl_seconds=LEASE_TTL_SECONDS)
    if lease is None:
        return None

    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE attempt SET status = 'leased', leased_at = %s WHERE id = %s", (now, attempt_id)
        )
    conn.commit()

    heartbeat_stop = threading.Event()
    lease_lost = threading.Event()
    heartbeat = threading.Thread(
        target=_renew_lease_until_stopped,
        args=(lease, heartbeat_stop, lease_lost),
        name=f"runengine-lease-{attempt_id}", daemon=True,
    )
    heartbeat.start()
    try:
        work_dir = workspace_root / str(attempt_id)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attempt SET status = 'preparing' WHERE id = %s", (attempt_id,)
            )
        conn.commit()
        runner_input = materialize_workspace(corpus_root, item_id, work_dir)

        started_at = datetime.now(UTC)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attempt SET status = 'running', started_at = %s WHERE id = %s",
                (started_at, attempt_id),
            )
        conn.commit()

        if not lease.renew(ttl_seconds=LEASE_TTL_SECONDS):
            log.error("lost %s lease mid-attempt %s", RESOURCE_NAME, attempt_id)
            _mark_terminal(conn, attempt_id, status="failed", reason="lost resource lease")
            return None

        outcome = executor(
            candidate_slug=candidate_slug, corpus_root=corpus_root, item_id=item_id,
            runner_input=runner_input, work_dir=work_dir, timeout=timeout,
            tool_version=tool_version, cancel_event=lease_lost,
        )

        heartbeat_stop.set()
        heartbeat.join()
        if lease_lost.is_set() or not lease.renew(ttl_seconds=LEASE_TTL_SECONDS):
            _mark_terminal(conn, attempt_id, status="failed", reason="lost resource lease")
            return None

        evaluated_at = datetime.now(UTC)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE attempt SET status = 'evaluating', evaluated_at = %s WHERE id = %s",
                (evaluated_at, attempt_id),
            )
        conn.commit()

        if outcome.ok:
            _persist_success_artifacts(conn, store, attempt_id, outcome)
            if oracle_root is not None:
                evaluate_and_persist(
                    conn, attempt_id=attempt_id, item_id=item_id, oracle_root=oracle_root,
                    findings=outcome.findings, novel_finding_judge=novel_finding_judge,
                )
            _mark_terminal(conn, attempt_id, status="succeeded", reason=None)
            return outcome

        if outcome.schema_drift:
            _mark_terminal(
                conn, attempt_id, status="invalid",
                reason=f"adapter output schema drift: {outcome.schema_drift_detail}",
            )
            return outcome

        failure_class = classify_failure(
            timed_out=outcome.timed_out, returncode=outcome.returncode,
            stdout=outcome.stdout, stderr=outcome.stderr, schema_drift=False,
        )
        status = "timed_out" if outcome.timed_out else "failed"
        _mark_terminal(conn, attempt_id, status=status, reason=f"{failure_class}: {outcome.stderr[:500]}")
        if failure_class == "transient":
            _maybe_create_retry(conn, store, attempt_id, model=model, config_hash=config_hash)
        return outcome
    except Exception as error:
        conn.rollback()
        log.exception("attempt %s crashed", attempt_id)
        _mark_terminal(
            conn, attempt_id, status="failed",
            reason=f"non_transient: {type(error).__name__}: {str(error)[:500]}",
        )
        raise
    finally:
        heartbeat_stop.set()
        heartbeat.join()
        lease.release()


def _mark_terminal(conn: psycopg.Connection, attempt_id: UUID, *, status: str, reason: str | None) -> None:
    """Record the terminal status and finish time for an attempt."""
    finished_at = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE attempt SET status = %s, terminal_reason = %s, finished_at = %s WHERE id = %s",
            (status, reason, finished_at, attempt_id),
        )
    conn.commit()


def _persist_success_artifacts(
    conn: psycopg.Connection, store: ArtifactStore, attempt_id: UUID, outcome: ToolExecutionOutcome
) -> None:
    """Store successful raw output and normalized findings as artifacts."""
    raw_stored = store.put(outcome.raw_output, content_type="application/json")
    findings_bytes = json.dumps(
        [f.model_dump(mode="json") for f in outcome.findings], sort_keys=True
    ).encode()
    findings_stored = store.put(findings_bytes, content_type="application/json")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO artifact (id, attempt_id, kind, sha256, s3_uri, mime_type, size_bytes)
            VALUES (%s, %s, 'raw_output', %s, %s, 'application/json', %s)
            """,
            (uuid4(), attempt_id, raw_stored.sha256, raw_stored.s3_uri, raw_stored.size_bytes),
        )
        cur.execute(
            """
            INSERT INTO artifact (id, attempt_id, kind, sha256, s3_uri, mime_type, size_bytes)
            VALUES (%s, %s, 'normalized_findings', %s, %s, 'application/json', %s)
            """,
            (
                uuid4(), attempt_id, findings_stored.sha256, findings_stored.s3_uri,
                findings_stored.size_bytes,
            ),
        )
    conn.commit()


def _maybe_create_retry(
    conn: psycopg.Connection, store: ArtifactStore, failed_attempt_id: UUID, *, model: str, config_hash: str
) -> UUID | None:
    """Create a fresh attempt when the failure is retryable within the cap."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT plan_id, item_id, candidate_version_id, sample_index, retry_of_attempt_id
            FROM attempt WHERE id = %s
            """,
            (failed_attempt_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        plan_id, item_id, candidate_version_id, sample_index, retry_of = row
        original_id = retry_of or failed_attempt_id
        cur.execute("SELECT retry_cap FROM execution_plan WHERE id = %s", (plan_id,))
        (retry_cap,) = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM attempt WHERE id = %s OR retry_of_attempt_id = %s",
            (original_id, original_id),
        )
        (retry_count,) = cur.fetchone()
        retry_count -= 1  # exclude the original attempt itself
        if not should_retry(retry_count=retry_count, retry_cap=retry_cap):
            return None
        cur.execute(
            "SELECT suite_version_digest, score_policy_version, resource_profile FROM execution_plan WHERE id = %s",
            (plan_id,),
        )
        suite_version_digest, score_policy_version, resource_profile = cur.fetchone()

    new_attempt_id = uuid4()
    created_at = datetime.now(UTC)
    manifest = _build_manifest(
        attempt_id=new_attempt_id,
        suite_version_digest=suite_version_digest,
        item_id=item_id,
        candidate_version_id=candidate_version_id,
        model=model,
        config_hash=config_hash,
        score_policy_version=score_policy_version,
        resource_profile=resource_profile,
        created_at=created_at,
    )
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest_digest = sha256(manifest_bytes).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attempt
                (id, plan_id, item_id, candidate_version_id, sample_index, retry_of_attempt_id,
                 capability_profile_id, comparison_axis, status, manifest_digest, queued_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'end_to_end_agent', 'queued', %s, %s)
            """,
            (
                new_attempt_id, plan_id, item_id, candidate_version_id, sample_index, original_id,
                str(CAPABILITY_PROFILE_ID), manifest_digest, created_at,
            ),
        )
        stored = store.put(manifest_bytes, content_type="application/json")
        cur.execute(
            """
            INSERT INTO artifact (id, attempt_id, kind, sha256, s3_uri, mime_type, size_bytes)
            VALUES (%s, %s, 'manifest', %s, %s, 'application/json', %s)
            """,
            (uuid4(), new_attempt_id, stored.sha256, stored.s3_uri, stored.size_bytes),
        )
    conn.commit()
    log.info("retrying attempt %s as %s", failed_attempt_id, new_attempt_id)
    return new_attempt_id


class NovelFindingJudge(Protocol):
    def evaluate_novel_finding(self, finding: Finding, *, item_context: str) -> NovelFindingVerdict: ...


def _load_gold_labels(oracle_root: Path, item_id: str) -> list[ProtectedDefectLabel]:
    """0 or 1 label per item in the current corpus model (an item with no
    ground-truth.yaml is a clean control)."""
    label_file = oracle_root / item_id / "ground-truth.yaml"
    if not label_file.is_file():
        return []
    return [validate_protected_defect_label(label_file)]


def evaluate_and_persist(
    conn: psycopg.Connection,
    *,
    attempt_id: UUID,
    item_id: str,
    oracle_root: Path,
    findings: tuple[Finding, ...],
    novel_finding_judge: NovelFindingJudge | None = None,
) -> AttemptEvaluation:
    """FR-009/FR-009a/FR-009b: classify findings, persist evaluation rows and
    attempt-level Oracle counts, and triage unmatched findings for the
    Gold-label-candidate pipeline. Never called from inside a runner's
    workspace — only after a successful Attempt, against the protected Oracle.
    """
    gold_labels = _load_gold_labels(oracle_root, item_id)
    evaluation = evaluate_attempt_findings(list(findings), gold_labels)
    findings_by_id = {finding.id: finding for finding in findings}

    with conn.cursor() as cur:
        for finding_evaluation in evaluation.finding_evaluations:
            evaluation_row_id = uuid4()
            cur.execute(
                """
                INSERT INTO evaluation
                    (id, attempt_id, evaluator_version, finding_id, gold_label_id, outcome)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    evaluation_row_id, attempt_id, EVALUATOR_VERSION,
                    finding_evaluation.finding_id, finding_evaluation.gold_label_id,
                    finding_evaluation.outcome,
                ),
            )
            if finding_evaluation.outcome == "unmatched_gold":
                judge = novel_finding_judge or make_novel_finding_judge()
                finding = findings_by_id[finding_evaluation.finding_id]
                verdict = judge.evaluate_novel_finding(finding, item_context=item_id)
                review_id = record_novel_finding_review(
                    conn, evaluation_id=evaluation_row_id, verdict=verdict
                )
                if verdict.verdict == "plausible_novel_defect":
                    propose_gold_label_candidate(
                        conn, novel_finding_review_id=review_id, item_id=item_id,
                        finding=finding, judge_reasoning=verdict.reasoning,
                    )
        cur.execute(
            """
            UPDATE attempt
            SET oracle_label_count = %s, matched_gold_label_count = %s,
                missed_gold_label_count = %s
            WHERE id = %s
            """,
            (
                evaluation.oracle_label_count, evaluation.matched_gold_label_count,
                evaluation.missed_gold_label_count, attempt_id,
            ),
        )
    conn.commit()
    return evaluation
