"""Durable single-capacity resource leases for the local Run Engine worker."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class SqliteResourceLeaseStore:
    """SQLite-backed lease store shared by independent workers on one GPU host."""

    def __init__(self, database: Path, *, now: Callable[[], float] = time.time) -> None:
        self._database = database
        self._now = now
        self._initialise()

    def acquire(self, resource: str, holder: str, *, ttl_seconds: float) -> ResourceLease | None:
        """Atomically acquire one resource, or return ``None`` while it is leased."""
        if not resource or not holder:
            raise ValueError("Resource and holder must be non-empty")
        if ttl_seconds <= 0:
            raise ValueError("Lease TTL must be positive")
        now = self._now()
        token = str(uuid4())
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT expires_at FROM resource_leases WHERE resource = ?", (resource,)
            ).fetchone()
            if row is not None and row[0] > now:
                connection.rollback()
                return None
            connection.execute("DELETE FROM resource_leases WHERE resource = ?", (resource,))
            connection.execute(
                "INSERT INTO resource_leases (resource, holder, token, expires_at) VALUES (?, ?, ?, ?)",
                (resource, holder, token, now + ttl_seconds),
            )
            connection.commit()
        finally:
            connection.close()
        return ResourceLease(self, resource, holder, token)

    def _release(self, resource: str, holder: str, token: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "DELETE FROM resource_leases WHERE resource = ? AND holder = ? AND token = ?",
                (resource, holder, token),
            )
            connection.commit()
        finally:
            connection.close()

    def _renew(self, resource: str, holder: str, token: str, *, ttl_seconds: float) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("Lease TTL must be positive")
        now = self._now()
        connection = self._connect()
        try:
            cursor = connection.execute(
                """
                UPDATE resource_leases
                SET expires_at = ?
                WHERE resource = ? AND holder = ? AND token = ? AND expires_at > ?
                """,
                (now + ttl_seconds, resource, holder, token, now),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def _initialise(self) -> None:
        self._database.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS resource_leases (
                    resource TEXT PRIMARY KEY,
                    holder TEXT NOT NULL,
                    token TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database, timeout=5, isolation_level=None)


@dataclass(frozen=True)
class ResourceLease:
    """Opaque ownership token that can release only the lease it acquired."""

    _store: SqliteResourceLeaseStore
    resource: str
    holder: str
    token: str

    def release(self) -> None:
        self._store._release(self.resource, self.holder, self.token)

    def renew(self, *, ttl_seconds: float) -> bool:
        """Extend this live lease, returning false if it was lost or expired."""
        return self._store._renew(
            self.resource, self.holder, self.token, ttl_seconds=ttl_seconds
        )
