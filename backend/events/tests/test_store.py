"""Store contract: ordering, append-only immutability, cursoring, filters."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from contracts.events.schema import Event, EventType, Severity
from backend.events.store import EventQuery, InMemoryEventStore


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


def test_seq_is_monotonic_and_total_order():
    store = InMemoryEventStore()
    seqs = [store.append(_mk(event_id=f"e{i}")).seq for i in range(5)]
    assert seqs == [1, 2, 3, 4, 5]


def test_ordering_by_seq_not_timestamp():
    # Out-of-order timestamps must still return in append (seq) order.
    store = InMemoryEventStore()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store.append(_mk(event_id="late", occurred_at=base + timedelta(hours=5)))
    store.append(_mk(event_id="early", occurred_at=base))
    rows = store.query(EventQuery(tenant_id="t"))
    assert [r.event.event_id for r in rows] == ["late", "early"]
    assert [r.seq for r in rows] == [1, 2]


def test_store_has_no_mutation_methods():
    # Append-only is structural: the interface exposes no update/delete.
    store = InMemoryEventStore()
    for forbidden in ("update", "delete", "remove", "set", "save"):
        assert not hasattr(store, forbidden)


def test_stored_event_is_frozen():
    store = InMemoryEventStore()
    stored = store.append(_mk())
    with pytest.raises(dataclasses.FrozenInstanceError):
        stored.seq = 99  # type: ignore[misc]


def test_returned_events_are_copies_cannot_mutate_log():
    store = InMemoryEventStore()
    store.append(_mk(event_id="x", payload={"a": 1}))
    got = store.query(EventQuery(tenant_id="t"))[0]
    got.event.payload["a"] = 999  # mutate the copy
    again = store.query(EventQuery(tenant_id="t"))[0]
    assert again.event.payload["a"] == 1  # persisted log untouched


def test_after_seq_cursor():
    store = InMemoryEventStore()
    for i in range(5):
        store.append(_mk(event_id=f"e{i}"))
    rows = store.query(EventQuery(tenant_id="t", after_seq=3))
    assert [r.seq for r in rows] == [4, 5]


def test_limit_returns_newest_in_chronological_order():
    store = InMemoryEventStore()
    for i in range(5):
        store.append(_mk(event_id=f"e{i}"))
    rows = store.query(EventQuery(tenant_id="t", limit=2))
    assert [r.seq for r in rows] == [4, 5]


def test_type_and_severity_filters():
    store = InMemoryEventStore()
    store.append(_mk(event_id="a", type=EventType.CALL_STARTED))
    store.append(_mk(event_id="b", type=EventType.GUARDRAIL_TRIPPED, severity=Severity.WARNING))
    only_gr = store.query(EventQuery(tenant_id="t", types=frozenset({EventType.GUARDRAIL_TRIPPED})))
    assert [r.event.event_id for r in only_gr] == ["b"]
    warns = store.query(EventQuery(tenant_id="t", severities=frozenset({Severity.WARNING})))
    assert [r.event.event_id for r in warns] == ["b"]


def test_time_window_filter():
    store = InMemoryEventStore()
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    store.append(_mk(event_id="old", occurred_at=base))
    store.append(_mk(event_id="mid", occurred_at=base + timedelta(hours=2)))
    store.append(_mk(event_id="new", occurred_at=base + timedelta(hours=4)))
    rows = store.query(EventQuery(
        tenant_id="t", since=base + timedelta(hours=1), until=base + timedelta(hours=4)
    ))
    assert [r.event.event_id for r in rows] == ["mid"]  # since inclusive, until exclusive


def test_get_by_id_and_tenant_scope():
    store = InMemoryEventStore()
    store.append(_mk(tenant="a", event_id="x"))
    assert store.get("a", "x") is not None
    assert store.get("b", "x") is None  # not-yours == not-found (no existence leak)
    assert store.get("a", "nope") is None
