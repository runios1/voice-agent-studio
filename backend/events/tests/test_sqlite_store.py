"""SQLiteEventStore — same `EventStore` Protocol as `InMemoryEventStore`
(`test_store.py`); this file focuses on what's specific to the SQLite impl:
durability across a reopen and the append-only trigger backstop."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlite3

import pytest

from contracts.events.schema import Event, EventType, Severity
from backend.events.store import EventQuery
from backend.events.sqlite_store import SQLiteEventStore


def _mk(tenant="t", type=EventType.CALL_STARTED, **kw) -> Event:
    return Event(
        event_id=kw.pop("event_id", f"e-{id(object())}"),
        type=type,
        occurred_at=kw.pop("occurred_at", datetime.now(timezone.utc)),
        severity=kw.pop("severity", Severity.INFO),
        tenant_id=tenant,
        payload=kw.pop("payload", {}),
        **kw,
    )


@pytest.fixture
def path(tmp_path) -> str:
    return str(tmp_path / "events.db")


def test_append_assigns_monotonic_seq(path):
    store = SQLiteEventStore(path)
    seqs = [store.append(_mk(event_id=f"e{i}")).seq for i in range(3)]
    assert seqs == [1, 2, 3]


def test_query_is_tenant_scoped(path):
    store = SQLiteEventStore(path)
    store.append(_mk(tenant="acme", event_id="a"))
    store.append(_mk(tenant="globex", event_id="b"))
    rows = store.query(EventQuery(tenant_id="acme"))
    assert [r.event.event_id for r in rows] == ["a"]


def test_get_by_event_id_scoped_to_tenant(path):
    store = SQLiteEventStore(path)
    store.append(_mk(tenant="acme", event_id="a"))
    assert store.get("acme", "a") is not None
    assert store.get("globex", "a") is None  # missing OR not yours — indistinguishable


def test_after_seq_cursor(path):
    store = SQLiteEventStore(path)
    for i in range(3):
        store.append(_mk(event_id=f"e{i}"))
    rows = store.query(EventQuery(tenant_id="t", after_seq=1))
    assert [r.seq for r in rows] == [2, 3]


def test_payload_round_trips_as_json(path):
    store = SQLiteEventStore(path)
    store.append(_mk(event_id="e0", payload={"nested": {"a": 1}, "list": [1, 2]}))
    row = store.get("t", "e0")
    assert row.event.payload == {"nested": {"a": 1}, "list": [1, 2]}


def test_persists_across_reopen(path):
    first = SQLiteEventStore(path)
    first.append(_mk(event_id="e0"))
    reopened = SQLiteEventStore(path)
    rows = reopened.query(EventQuery(tenant_id="t"))
    assert [r.event.event_id for r in rows] == ["e0"]


def test_append_only_blocks_update_at_the_database_level(path):
    store = SQLiteEventStore(path)
    store.append(_mk(event_id="e0"))
    conn = store._connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE events SET severity = 'critical' WHERE event_id = 'e0'")
    finally:
        conn.close()


def test_append_only_blocks_delete_at_the_database_level(path):
    store = SQLiteEventStore(path)
    store.append(_mk(event_id="e0"))
    conn = store._connect()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM events WHERE event_id = 'e0'")
    finally:
        conn.close()
