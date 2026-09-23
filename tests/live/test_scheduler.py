from __future__ import annotations

from benchmark.live import LiveChallengerScheduler, LivePRSnapshot


def test_runs_known_challengers_in_a_stable_order_under_the_callers_lease() -> None:
    scheduler = LiveChallengerScheduler()
    snapshot = LivePRSnapshot(
        repository="haexmas/holzi",
        pr_number=27,
        base_sha="a" * 40,
        head_sha="b" * 40,
        diff_sha256="c" * 64,
    )
    received: list[str] = []

    attempts = scheduler.run(
        snapshot,
        {
            "pr-agent": lambda _snapshot: received.append("pr-agent"),
            "gito": lambda _snapshot: received.append("gito"),
        },
    )

    assert received == ["gito", "pr-agent"]
    assert [attempt.head_sha for attempt in attempts] == [snapshot.head_sha, snapshot.head_sha]
