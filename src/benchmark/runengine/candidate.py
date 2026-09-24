"""CandidateVersion registration.

Bare registration only for now (US1 prerequisite: `attempt.candidate_version_id`
is a required foreign key). The capability-probe gate that blocks an unprobed
or failed version from scored use (FR-012, US4) is added on top of this same
table in a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg


@dataclass(frozen=True)
class CandidateVersion:
    id: UUID
    slug: str
    tool_version: str
    package_digest: str
    model_endpoint_config_hash: str
    capability_probe_status: str


def register_candidate(
    conn: psycopg.Connection,
    *,
    slug: str,
    tool_version: str,
    package_digest: str,
    model_endpoint_config_hash: str,
) -> CandidateVersion:
    """Register a new candidate version row (always `capability_probe_status='pending'`)."""
    if slug not in ("gito", "pr-agent"):
        raise ValueError(f"Unknown candidate slug: {slug!r}")
    candidate_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO candidate_version
                (id, slug, tool_version, package_digest, model_endpoint_config_hash,
                 capability_probe_status)
            VALUES (%s, %s, %s, %s, %s, 'pending')
            """,
            (candidate_id, slug, tool_version, package_digest, model_endpoint_config_hash),
        )
    conn.commit()
    return CandidateVersion(
        id=candidate_id, slug=slug, tool_version=tool_version, package_digest=package_digest,
        model_endpoint_config_hash=model_endpoint_config_hash, capability_probe_status="pending",
    )


def get_candidate(conn: psycopg.Connection, candidate_version_id: UUID) -> CandidateVersion | None:
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
