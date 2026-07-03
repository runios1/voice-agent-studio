"""Analytics — query-computed roll-ups over the append-only log."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from contracts.events.schema import Event, EventType, Severity
from backend.events.analytics import aggregate, time_series
from backend.events.store import EventQuery, InMemoryEventStore
from .conftest import TENANT, OTHER


def _mk(store, type, tenant=TENANT, campaign_id=None, payload=None, severity=Severity.INFO,
        occurred_at=None, eid=None):
    ev = Event(
        event_id=eid or f"e{store.query(EventQuery(tenant_id=tenant)).__len__()}-{type.value}",
        type=type, occurred_at=occurred_at or datetime.now(timezone.utc),
        severity=severity, tenant_id=tenant, campaign_id=campaign_id, payload=payload or {},
    )
    return store.append(ev)


def test_aggregate_counts_by_type_and_outcome():
    store = InMemoryEventStore()
    _mk(store, EventType.CALL_STARTED, campaign_id="c1", eid="1")
    _mk(store, EventType.LEAD_OUTCOME, campaign_id="c1", payload={"outcome": "qualified"}, eid="2")
    _mk(store, EventType.LEAD_OUTCOME, campaign_id="c1", payload={"outcome": "no_answer"}, eid="3")
    _mk(store, EventType.LEAD_OUTCOME, campaign_id="c1", payload={"outcome": "qualified"}, eid="4")
    agg = aggregate(store, EventQuery(tenant_id=TENANT))
    assert agg.total == 4
    assert agg.by_type["lead.outcome"] == 3
    assert agg.lead_outcomes == {"qualified": 2, "no_answer": 1}
    assert agg.by_campaign["c1"] == 4


def test_aggregate_guardrail_trips():
    store = InMemoryEventStore()
    _mk(store, EventType.GUARDRAIL_TRIPPED, payload={"guardrail": "dnc"}, eid="1")
    _mk(store, EventType.GUARDRAIL_TRIPPED, payload={"guardrail": "dnc"}, eid="2")
    _mk(store, EventType.GUARDRAIL_TRIPPED, payload={"guardrail": "calling_hours"}, eid="3")
    agg = aggregate(store, EventQuery(tenant_id=TENANT))
    assert agg.guardrail_trips == {"dnc": 2, "calling_hours": 1}


def test_aggregate_is_tenant_scoped():
    store = InMemoryEventStore()
    _mk(store, EventType.CALL_STARTED, tenant=TENANT, eid="a")
    _mk(store, EventType.CALL_STARTED, tenant=OTHER, eid="b")
    assert aggregate(store, EventQuery(tenant_id=TENANT)).total == 1


def test_time_series_buckets():
    store = InMemoryEventStore()
    base = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    _mk(store, EventType.CALL_STARTED, occurred_at=base, eid="a")
    _mk(store, EventType.CALL_STARTED, occurred_at=base + timedelta(minutes=30), eid="b")
    _mk(store, EventType.CALL_STARTED, occurred_at=base + timedelta(hours=2), eid="c")
    buckets = time_series(store, EventQuery(tenant_id=TENANT), bucket_seconds=3600)
    assert len(buckets) == 2  # hour 0 (2 events) and hour 2 (1 event); hour 1 omitted
    assert buckets[0].count == 2
    assert buckets[1].count == 1
