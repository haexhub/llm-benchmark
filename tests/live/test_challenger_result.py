from __future__ import annotations

import json

from benchmark.live import (
    LiveChallengerAttempt,
    LiveChallengerResult,
    LiveObservationStore,
    LivePRSnapshot,
)
from benchmark.models import Finding


def test_persists_a_successful_challenger_attempt_and_its_findings(tmp_path) -> None:
    observation = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    result = LiveChallengerResult(
        attempt=LiveChallengerAttempt(
            challenger="gito",
            base_sha=observation.base_sha,
            head_sha=observation.head_sha,
            state="succeeded",
            duration_seconds=12.5,
        ),
        findings=[
            Finding(
                tool="gito",
                file="src/service.py",
                line_start=12,
                line_end=12,
                severity="major",
                category="bug",
                title="Validate the page size",
                body="A negative page size reaches the database query.",
            )
        ],
    )
    store = LiveObservationStore(tmp_path)
    store.record(observation)

    persisted = store.record_challenger_result(observation, result)

    assert persisted.created is True
    artifact = json.loads(store.challenger_path(observation, "gito").read_text())
    assert artifact["attempt"]["head_sha"] == observation.head_sha
    assert artifact["findings"][0]["tool"] == "gito"
