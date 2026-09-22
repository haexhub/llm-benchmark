from __future__ import annotations

from benchmark.live import SqliteResourceLeaseStore


def test_allows_only_one_worker_to_hold_the_local_gpu_lease(tmp_path) -> None:
    database = tmp_path / "run-engine.sqlite3"
    first_worker = SqliteResourceLeaseStore(database)
    second_worker = SqliteResourceLeaseStore(database)

    first_lease = first_worker.acquire("local-94gb-gpu", "worker-a", ttl_seconds=60)
    blocked_lease = second_worker.acquire("local-94gb-gpu", "worker-b", ttl_seconds=60)

    assert first_lease is not None
    assert blocked_lease is None
    first_lease.release()
    assert second_worker.acquire("local-94gb-gpu", "worker-b", ttl_seconds=60) is not None


def test_recovers_a_lease_after_its_worker_stops_renewing_it(tmp_path) -> None:
    clock = [100.0]
    database = tmp_path / "run-engine.sqlite3"
    first_worker = SqliteResourceLeaseStore(database, now=lambda: clock[0])
    second_worker = SqliteResourceLeaseStore(database, now=lambda: clock[0])

    assert first_worker.acquire("local-94gb-gpu", "worker-a", ttl_seconds=60) is not None
    clock[0] = 160.0

    assert second_worker.acquire("local-94gb-gpu", "worker-b", ttl_seconds=60) is not None


def test_renews_only_the_current_holders_lease(tmp_path) -> None:
    clock = [100.0]
    database = tmp_path / "run-engine.sqlite3"
    first_worker = SqliteResourceLeaseStore(database, now=lambda: clock[0])
    second_worker = SqliteResourceLeaseStore(database, now=lambda: clock[0])
    lease = first_worker.acquire("local-94gb-gpu", "worker-a", ttl_seconds=60)
    assert lease is not None

    clock[0] = 150.0
    assert lease.renew(ttl_seconds=60) is True
    clock[0] = 161.0

    assert second_worker.acquire("local-94gb-gpu", "worker-b", ttl_seconds=60) is None
