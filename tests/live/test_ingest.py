from __future__ import annotations

import hashlib

from benchmark.live import LiveObservationStore, LivePRIngestor
from benchmark.models import LiveRepositoryIntegration


def test_ingests_an_enabled_pr_as_an_immutable_diff_snapshot(tmp_path) -> None:
    integration = LiveRepositoryIntegration(owner="haexmas", name="holzi", enabled=True)
    store = LiveObservationStore(tmp_path)
    ingestor = LivePRIngestor(
        store,
        fetch_refs=lambda _owner, _name, _pr: {"base_sha": "a" * 40, "head_sha": "b" * 40},
        fetch_diff=lambda _owner, _name, base, head: f"diff {base} {head}\n",
    )

    recorded = ingestor.ingest(integration, 27)

    assert recorded.created is True
    assert recorded.observation.snapshot.diff_sha256 == hashlib.sha256(
        ("diff " + "a" * 40 + " " + "b" * 40 + "\n").encode()
    ).hexdigest()
    assert store.diff_path(recorded.observation.snapshot).read_text().startswith("diff ")
