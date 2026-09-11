"""US3 T048: manual reviews override automatic classifications, orphan reviews warn quietly."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from benchmark.matching.aggregator import apply_manual_reviews, load_manual_reviews
from benchmark.models import JudgeVerdict, ManualReview, Match


def _v():
    return JudgeVerdict(same=True, confidence=0.9, reason="x", judge_model="m", prompt_hash="0" * 64)


def test_load_manual_reviews_from_file(tmp_path: Path) -> None:
    mid = uuid4()
    (tmp_path / "manual_review.json").write_text(
        json.dumps({
            "schema_version": "1",
            "reviews": [{
                "match_id": str(mid),
                "decision": "different",
                "reviewer": "me",
                "ts": "2026-09-01T12:00:00+00:00",
            }]
        })
    )
    reviews = load_manual_reviews(tmp_path / "manual_review.json")
    assert len(reviews) == 1
    assert reviews[0].match_id == mid


def test_load_manual_reviews_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_manual_reviews(tmp_path / "nope.json") == []


def test_apply_manual_override_flips_classification() -> None:
    m = Match(a_id=uuid4(), b_id=uuid4(), structural_overlap_lines=1, verdict=_v(), classification="same")
    override = ManualReview(match_id=m.id, decision="different", reviewer="me", ts=datetime.now(UTC))
    updated = apply_manual_reviews([m], [override])
    assert updated[0].classification == "different"


def test_orphan_manual_review_ignored_no_crash() -> None:
    m = Match(a_id=uuid4(), b_id=uuid4(), structural_overlap_lines=1, verdict=_v(), classification="same")
    orphan = ManualReview(match_id=uuid4(), decision="different", reviewer="me", ts=datetime.now(UTC))
    updated = apply_manual_reviews([m], [orphan])
    assert updated[0].classification == "same"  # unchanged
