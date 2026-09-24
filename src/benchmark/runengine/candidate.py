"""CandidateVersion registration and capability-probe gating (FR-012).

The probe reuses the exact reachability check `benchmark check` already runs
(`uv tool run --from <package> <tool> --help`, research.md R8) — persisted as
a structured result instead of only printed to the console.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Json

ProbeStatus = Literal["pending", "passed", "failed"]

_PACKAGE_BY_SLUG = {"gito": "gito.bot", "pr-agent": "pr-agent"}


@dataclass(frozen=True)
class CandidateVersion:
    id: UUID
    slug: str
    tool_version: str
    package_digest: str
    model_endpoint_config_hash: str
    capability_probe_status: ProbeStatus


class CandidateNotUsable(Exception):
    """A plan referenced a candidate version whose probe hasn't passed (FR-012)."""


def run_capability_probe(slug: str, *, timeout: int = 120) -> tuple[ProbeStatus, dict]:
    """`uv tool run --from <package> <slug> --help` must exit 0 to pass."""
    package = _PACKAGE_BY_SLUG[slug]
    try:
        proc = subprocess.run(
            ["uv", "tool", "run", "--from", package, slug, "--help"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        return "failed", {"error": "timeout", "detail": str(error)}
    passed = proc.returncode == 0
    return (
        "passed" if passed else "failed",
        {"returncode": proc.returncode, "stderr_tail": proc.stderr[-500:]},
    )


def register_candidate(
    conn: psycopg.Connection,
    *,
    slug: str,
    tool_version: str,
    package_digest: str,
    model_endpoint_config_hash: str,
) -> CandidateVersion:
    """Register a candidate version and run its capability probe immediately."""
    if slug not in _PACKAGE_BY_SLUG:
        raise ValueError(f"Unknown candidate slug: {slug!r}")
    status, probe_result = run_capability_probe(slug)
    candidate_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO candidate_version
                (id, slug, tool_version, package_digest, model_endpoint_config_hash,
                 capability_probe_status, capability_probe_result)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                candidate_id, slug, tool_version, package_digest, model_endpoint_config_hash,
                status, Json(probe_result),
            ),
        )
    conn.commit()
    return CandidateVersion(
        id=candidate_id, slug=slug, tool_version=tool_version, package_digest=package_digest,
        model_endpoint_config_hash=model_endpoint_config_hash, capability_probe_status=status,
    )


def get_candidate(conn: psycopg.Connection, candidate_version_id: UUID) -> CandidateVersion | None:
    """Load a candidate version and its capability-probe status from the database."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, slug, tool_version, package_digest, model_endpoint_config_hash,
                   capability_probe_status
            FROM candidate_version WHERE id = %s
            """,
            (candidate_version_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return CandidateVersion(
        id=row[0], slug=row[1], tool_version=row[2], package_digest=row[3],
        model_endpoint_config_hash=row[4], capability_probe_status=row[5],
    )


def require_passed(candidate: CandidateVersion) -> None:
    """FR-012: a plan must never reference a pending/failed candidate version."""
    if candidate.capability_probe_status != "passed":
        raise CandidateNotUsable(
            f"candidate_version {candidate.id} ({candidate.slug}) has capability_probe_status="
            f"{candidate.capability_probe_status!r}, not 'passed' — cannot be used in a scored plan"
        )
