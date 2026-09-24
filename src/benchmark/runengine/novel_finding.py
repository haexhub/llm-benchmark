"""FR-009a/FR-009b: judge triage for findings beyond the Gold set, and their
export as Gold-label candidates for feature 003's curator pipeline.

This module never writes anything but `status='proposed'` — promoting a
candidate into an actual Gold label is exclusively 003's curator-approval
pipeline's job (constitution Principle I: never retroactively rewrite the
Gold set of a suite version attempts already scored against).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import psycopg

from benchmark.matching.judge import NovelFindingVerdict
from benchmark.models import Finding


def record_novel_finding_review(
    conn: psycopg.Connection, *, evaluation_id: UUID, verdict: NovelFindingVerdict
) -> UUID:
    """Persist a judge verdict on one `unmatched_gold` finding (FR-009a)."""
    review_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO novel_finding_review
                (id, evaluation_id, judge_model, verdict, reasoning, prompt_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                review_id, evaluation_id, verdict.judge_model, verdict.verdict,
                verdict.reasoning, verdict.prompt_hash,
            ),
        )
    conn.commit()
    return review_id


def propose_gold_label_candidate(
    conn: psycopg.Connection,
    *,
    novel_finding_review_id: UUID,
    item_id: str,
    finding: Finding,
    judge_reasoning: str,
) -> UUID:
    """FR-009b: package a `plausible_novel_defect` verdict for curator review."""
    candidate_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gold_label_candidate
                (id, novel_finding_review_id, item_id, location_file, location_line_start,
                 location_line_end, finding_summary, judge_reasoning, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'proposed')
            """,
            (
                candidate_id, novel_finding_review_id, item_id, finding.file,
                finding.line_start, finding.line_end, finding.title, judge_reasoning,
            ),
        )
    conn.commit()
    return candidate_id
