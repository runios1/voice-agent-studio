"""Shared SQLite connection helper — the zero-config persistence default.

`persistence.py` picks Postgres when `DATABASE_URL` is set; otherwise every store
(config, orchestrator, events, auth) falls back to SQLite rather than in-memory, so
a local/dev run actually remembers agents, campaigns, events and user accounts
across restarts with no external service to stand up. One file, several tables;
WAL mode lets concurrent readers coexist with the single writer.

`connect()` opens a short-lived connection per call (same posture as the Postgres
repositories: `with self._connect() as conn ...`). Compare-and-swap sections use
`BEGIN IMMEDIATE` to get SQLite's write lock atomically instead of Postgres's
`SELECT ... FOR UPDATE` (SQLite has no row-level locking).
"""

from __future__ import annotations

import os
import sqlite3

_DEFAULT_PATH = "./.data/vas.db"


def sqlite_path() -> str:
    return os.getenv("SQLITE_DB_PATH", _DEFAULT_PATH)


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or sqlite_path()
    directory = os.path.dirname(p)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def begin_immediate(conn: sqlite3.Connection) -> None:
    """Acquire SQLite's write lock up front so a compare-and-swap read-then-write
    is atomic (the Postgres impls get this from `FOR UPDATE`)."""
    conn.execute("BEGIN IMMEDIATE")
