"""Live bus — subscribers get matching events; slow ones don't block the publisher."""

from __future__ import annotations

import asyncio

from contracts.events.schema import EventType
from backend.events.bus import InMemoryEventBus
from backend.events.store import EventQuery, InMemoryEventStore
from contracts.events.schema import Event, Severity
from datetime import datetime, timezone
from .conftest import TENANT


def _stored(store, tenant=TENANT, type=EventType.CALL_STARTED, campaign_id=None, eid="e"):
    ev = Event(
        event_id=eid, type=type, occurred_at=datetime.now(timezone.utc),
        severity=Severity.INFO, tenant_id=tenant, campaign_id=campaign_id, payload={},
    )
    return store.append(ev)


async def test_subscriber_receives_live_events():
    store, bus = InMemoryEventStore(), InMemoryEventBus()
    sub = bus.subscribe(EventQuery(tenant_id=TENANT))
    await bus.publish(_stored(store, eid="a"))
    await bus.publish(_stored(store, eid="b"))
    got = []
    async for s in sub:
        got.append(s.event.event_id)
        if len(got) == 2:
            sub.close()
    assert got == ["a", "b"]


async def test_filter_applies_on_subscription():
    store, bus = InMemoryEventStore(), InMemoryEventBus()
    sub = bus.subscribe(EventQuery(tenant_id=TENANT, campaign_id="c1"))
    await bus.publish(_stored(store, campaign_id="c2", eid="skip"))
    await bus.publish(_stored(store, campaign_id="c1", eid="keep"))
    got = []
    async for s in sub:
        got.append(s.event.event_id)
        sub.close()
    assert got == ["keep"]


async def test_close_removes_subscriber():
    bus = InMemoryEventBus()
    sub = bus.subscribe(EventQuery(tenant_id=TENANT))
    assert bus.subscriber_count == 1
    sub.close()
    assert bus.subscriber_count == 0


async def test_slow_subscriber_drops_oldest_never_blocks_publisher():
    store, bus = InMemoryEventStore(), InMemoryEventBus()
    # tiny queue so overflow is easy to trigger
    from backend.events.bus import Subscription
    sub = Subscription(bus, EventQuery(tenant_id=TENANT), maxsize=2)
    bus._subs.add(sub)
    # publish 5 without ever draining — must not hang or raise
    for i in range(5):
        await asyncio.wait_for(bus.publish(_stored(store, eid=f"e{i}")), timeout=1)
    assert sub.dropped >= 1  # oldest were dropped; publisher stayed live
