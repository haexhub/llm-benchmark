from __future__ import annotations

import hashlib

from benchmark.live import LiveObservationStore, LivePRIngestor, PullRequestEventAdapter
from benchmark.models import LiveRepositoryIntegration


def test_ingests_the_sha_pair_from_a_synchronize_event_not_current_pr_refs(tmp_path) -> None:
    integration = LiveRepositoryIntegration(owner="haexmas", name="holzi", enabled=True)
    store = LiveObservationStore(tmp_path)
    ingestor = LivePRIngestor(
        store,
        fetch_refs=lambda _owner, _name, _pr: (_ for _ in ()).throw(AssertionError("must not fetch mutable refs")),
        fetch_diff=lambda _owner, _name, base, head: f"diff {base} {head}\n",
    )
    adapter = PullRequestEventAdapter({integration.slug: integration}, ingestor)
    payload = _payload(base="a" * 40, head="b" * 40)

    result = adapter.handle("pull_request", payload)

    assert result is not None
    assert result.observation.snapshot.base_sha == "a" * 40
    assert result.observation.snapshot.head_sha == "b" * 40
    assert result.observation.snapshot.diff_sha256 == hashlib.sha256(
        ("diff " + "a" * 40 + " " + "b" * 40 + "\n").encode()
    ).hexdigest()


def test_a_newer_head_creates_a_successor_observation_without_overwriting_the_old_one(tmp_path) -> None:
    integration = LiveRepositoryIntegration(owner="haexmas", name="holzi", enabled=True)
    store = LiveObservationStore(tmp_path)
    ingestor = LivePRIngestor(
        store,
        fetch_refs=lambda _owner, _name, _pr: {},
        fetch_diff=lambda _owner, _name, base, head: f"diff {base} {head}\n",
    )
    adapter = PullRequestEventAdapter({integration.slug: integration}, ingestor)

    original = adapter.handle("pull_request", _payload(base="a" * 40, head="b" * 40))
    successor = adapter.handle("pull_request", _payload(base="a" * 40, head="d" * 40))
    repeated_successor = adapter.handle("pull_request", _payload(base="a" * 40, head="d" * 40))

    assert original is not None and successor is not None and repeated_successor is not None
    assert original.created is True
    assert successor.created is True
    assert repeated_successor.created is False
    assert original.observation.id != successor.observation.id
    assert store.diff_path(original.observation.snapshot).is_file()
    assert store.diff_path(successor.observation.snapshot).is_file()


def _payload(*, base: str, head: str) -> dict:
    return {
        "action": "synchronize",
        "number": 27,
        "repository": {"full_name": "haexmas/holzi"},
        "pull_request": {"base": {"sha": base}, "head": {"sha": head}},
    }
