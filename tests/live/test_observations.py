from __future__ import annotations

from benchmark.live import LiveObservationStore, LivePRSnapshot


def test_records_one_immutable_observation_for_a_pr_revision(tmp_path) -> None:
    snapshot = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    store = LiveObservationStore(tmp_path)

    first = store.record(snapshot)
    repeated = store.record(snapshot)

    assert first.created is True
    assert repeated.created is False
    assert first.observation.id == repeated.observation.id
    assert first.observation.state == "queued"


def test_records_a_new_observation_when_the_base_changes_for_the_same_head(tmp_path) -> None:
    original = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    rebased = original.model_copy(update={"base_sha": "d" * 40, "diff_sha256": "e" * 64})
    store = LiveObservationStore(tmp_path)

    first = store.record(original)
    second = store.record(rebased)

    assert first.created is True
    assert second.created is True
    assert second.observation.id != first.observation.id


def test_transitions_the_observations_lifecycle_state_without_changing_its_identity(tmp_path) -> None:
    snapshot = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    store = LiveObservationStore(tmp_path)
    recorded = store.record(snapshot)

    updated = store.transition_state(snapshot, "running_challengers")

    assert updated.state == "running_challengers"
    assert updated.id == recorded.observation.id
    assert updated.created_at == recorded.observation.created_at
    assert store.record(snapshot).observation.state == "running_challengers"
