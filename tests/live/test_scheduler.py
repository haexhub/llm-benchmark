from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from benchmark.live import LiveChallengerScheduler, LivePRSnapshot


def test_serializes_challengers_across_two_live_observations() -> None:
    scheduler = LiveChallengerScheduler()
    first_snapshot = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    second_snapshot = first_snapshot.model_copy(
        update={"pr_number": 28, "head_sha": "d" * 40, "diff_sha256": "e" * 64}
    )
    state = {"active": 0, "max_active": 0, "received_heads": []}
    state_lock = threading.Lock()

    def challenger(snapshot: LivePRSnapshot) -> None:
        with state_lock:
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            state["received_heads"].append(snapshot.head_sha)
        time.sleep(0.02)
        with state_lock:
            state["active"] -= 1

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(scheduler.run, first_snapshot, {"gito": challenger})
        second = executor.submit(scheduler.run, second_snapshot, {"gito": challenger})
        first_attempts = first.result()
        second_attempts = second.result()

    assert state["max_active"] == 1
    assert {attempt.head_sha for attempt in first_attempts + second_attempts} == {
        first_snapshot.head_sha,
        second_snapshot.head_sha,
    }
