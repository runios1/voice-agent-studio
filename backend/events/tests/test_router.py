"""FastAPI surface — audit query/filter/export + live SSE stream, tenant-scoped."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from contracts.events.schema import EventType
from backend.events.router import create_app
from backend.events.service import EventService

TENANT = "tenant-acme"
OTHER = "tenant-globex"
H = {"X-Tenant-Id": TENANT}


def _seed(service: EventService) -> None:
    async def go():
        await service.emit(EventType.CALL_STARTED, tenant_id=TENANT, campaign_id="c1", payload={})
        await service.emit(
            EventType.GUARDRAIL_TRIPPED, tenant_id=TENANT, campaign_id="c1",
            payload={"guardrail": "dnc"},
        )
        await service.emit(EventType.CALL_STARTED, tenant_id=OTHER, payload={})

    asyncio.run(go())


@pytest.fixture
def service() -> EventService:
    svc = EventService()
    _seed(svc)
    return svc


@pytest.fixture
def client(service) -> TestClient:
    return TestClient(create_app(service))


def test_requires_auth(client):
    assert client.get("/events").status_code == 400  # no X-Tenant-Id


def test_query_is_tenant_scoped(client):
    rows = client.get("/events", headers=H).json()
    assert len(rows) == 2  # only TENANT's, not OTHER's
    assert all(r["event"]["tenant_id"] == TENANT for r in rows)


def test_type_filter(client):
    rows = client.get("/events", headers=H, params={"type": "guardrail.tripped"}).json()
    assert len(rows) == 1
    assert rows[0]["event"]["type"] == "guardrail.tripped"


def test_export_ndjson(client):
    resp = client.get("/events/export", headers=H)
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    lines = [l for l in resp.text.splitlines() if l]
    assert len(lines) == 2
    parsed = json.loads(lines[0])
    assert parsed["seq"] == 1 and parsed["event"]["tenant_id"] == TENANT


def test_analytics_endpoint(client):
    agg = client.get("/events/analytics", headers=H).json()
    assert agg["total"] == 2
    assert agg["guardrail_trips"] == {"dnc": 1}


async def test_sse_stream_backfills_then_tails_live_no_gap_no_dupe(service):
    # The SSE body generator is tested directly: httpx's ASGITransport buffers whole
    # responses, so it can't drive an infinite stream — but this generator IS the
    # streamed body, exercised here with a controllable disconnect callable.
    from backend.events.router import event_sse_stream
    from backend.events.store import EventQuery

    disconnected = {"v": False}

    async def is_disconnected():
        return disconnected["v"]

    # after_seq=1 -> backfill should yield only the guardrail event (seq 2); seq 3 is
    # another tenant and must not appear.
    q = EventQuery(tenant_id=TENANT, after_seq=1)
    gen = event_sse_stream(service, q, is_disconnected, heartbeat_seconds=0.05)

    async def next_id():
        async for frame in gen:
            if frame.startswith("id: "):
                return frame.split("\n", 1)[0]

    assert await asyncio.wait_for(next_id(), timeout=2) == "id: 2"  # backfilled

    # a fresh live event tails through the same generator (seq 4)
    await service.emit(
        EventType.LEAD_OUTCOME, tenant_id=TENANT, campaign_id="c1",
        payload={"outcome": "qualified"},
    )
    assert await asyncio.wait_for(next_id(), timeout=2) == "id: 4"  # live, deduped

    # a disconnect tears the stream down instead of leaking the subscription
    disconnected["v"] = True
    tail = [f async for f in gen]  # drains heartbeat(s) then stops
    assert all(not f.startswith("id: ") for f in tail)
    assert service._bus.subscriber_count == 0
