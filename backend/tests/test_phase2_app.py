"""INT-A — Phase-2 backend assembly (`backend/phase2_app.py`).

Proves the frozen contract `contracts/dashboard_http/README.md`:
  * §1 campaign routes are served under /api and seeded non-empty;
  * §4 the ONE EventService is threaded as the orchestrator's sink — a control action
    (pause) lands in the SAME log the dashboard reads (`GET /api/events`);
  * §0 both auth deps are overridden to a fixed dev user (no headers needed);
  * §2 the SSE stream body yields wrapped `{seq, event}` rows off the wired service;
  * §4b.5 the app boots WITHOUT INT-C (graceful inline-seed fallback), and picks up
    INT-C's `seed_and_run` when present.

Note (contract §DONE): httpx/ASGITransport BUFFERS whole responses, so the infinite
`/api/events/stream` is asserted via `event_sse_stream` directly, not over HTTP.
"""

from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient

from backend.events.router import event_sse_stream
from backend.events.store import EventQuery
from backend.phase2_app import DEV_USER, _resolve_seed_and_run, build_app


@pytest.fixture
def client() -> TestClient:
    # `with TestClient(app)` fires the lifespan, running the inline seed.
    with TestClient(build_app()) as c:
        yield c


# --------------------------------------------------------------------------- #
# §1 — campaigns served under /api, seeded non-empty, no auth headers (§0)
# --------------------------------------------------------------------------- #
def test_boots_and_serves_seeded_campaigns(client: TestClient):
    assert client.get("/api/health").json() == {"ok": True}

    campaigns = client.get("/api/campaigns").json()  # no auth headers (contract §0)
    assert len(campaigns) >= 1
    camp = campaigns[0]
    assert camp["state"] == "running"
    assert camp["tenant_id"] == DEV_USER

    leads = client.get(f"/api/campaigns/{camp['id']}/leads").json()
    assert len(leads) >= 1  # a few leads seeded


def test_campaign_detail_two_calls(client: TestClient):
    # The frontend composes CampaignDetail from these two calls (contract §1).
    cid = client.get("/api/campaigns").json()[0]["id"]
    assert client.get(f"/api/campaigns/{cid}").json()["id"] == cid
    assert isinstance(client.get(f"/api/campaigns/{cid}/leads").json(), list)


# --------------------------------------------------------------------------- #
# §4 — the shared sink: a control action lands in the log the dashboard reads
# --------------------------------------------------------------------------- #
def test_pause_emits_onto_the_shared_stream(client: TestClient):
    cid = client.get("/api/campaigns").json()[0]["id"]

    paused = client.post(f"/api/campaigns/{cid}/pause")
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"

    # PROOF OF SHARED SINK: the pause emitted a campaign.paused the events router serves.
    rows = client.get("/api/events", params={"type": "campaign.paused"}).json()
    assert rows, "pause did not land on the shared event log"
    row = rows[-1]
    assert set(row) == {"seq", "event"}  # rows are WRAPPED (contract §2)
    assert row["event"]["type"] == "campaign.paused"
    assert row["event"]["campaign_id"] == cid
    assert row["event"]["tenant_id"] == DEV_USER


def test_seed_start_event_on_the_log(client: TestClient):
    # The inline seed authorizes through the shared sink, so campaign.started is logged.
    rows = client.get("/api/events", params={"type": "campaign.started"}).json()
    assert rows and rows[0]["event"]["type"] == "campaign.started"


def test_emergency_stop_halts_all(client: TestClient):
    assert client.post("/api/emergency-stop").json() == {"stopped": True}
    # Every running campaign is now paused, and a critical campaign.paused is logged.
    assert all(c["state"] == "paused" for c in client.get("/api/campaigns").json())
    rows = client.get(
        "/api/events", params={"type": "campaign.paused", "severity": "critical"}
    ).json()
    assert any(r["event"]["payload"].get("reason") == "emergency_stop" for r in rows)


def test_events_query_and_export_wire_shapes(client: TestClient):
    # Every /api/events row is a {seq, event} envelope (never bare) — contract §2.
    for row in client.get("/api/events").json():
        assert set(row) == {"seq", "event"}
        assert "type" in row["event"] and "tenant_id" in row["event"]
    export = client.get("/api/events/export")
    assert export.headers["content-type"].startswith("application/x-ndjson")


# --------------------------------------------------------------------------- #
# §2 — the SSE stream body yields wrapped rows off the WIRED service
# (asserted directly; ASGITransport can't drive an infinite stream)
# --------------------------------------------------------------------------- #
async def test_stream_body_yields_wrapped_frames():
    app = build_app()
    events = app.state.events  # the same instance the /api/events/stream route serves

    # Emit through the shared service, then drain the backfill of the stream body.
    await events.emit("campaign.started", tenant_id=DEV_USER, campaign_id="camp_x",
                      payload={"lead_count": 1})

    async def disconnected() -> bool:
        return True  # break as soon as the backfill is drained (first idle tick)

    q = EventQuery(tenant_id=DEV_USER)
    frames = [f async for f in event_sse_stream(events, q, disconnected, heartbeat_seconds=0.01)]

    data_frames = [f for f in frames if f.startswith("id:")]
    assert data_frames, "stream body yielded no event frame"
    assert "event: event" in data_frames[0]
    assert '"seq"' in data_frames[0] and '"event"' in data_frames[0]


# --------------------------------------------------------------------------- #
# §4b.5 — seed resolution: inline fallback now, INT-C picked up when present
# --------------------------------------------------------------------------- #
def test_seed_resolution_falls_back_without_int_c():
    # When the demo module can't be imported (pre-INT-C, or a missing deploy), resolution
    # must return None so the inline seed is used. INT-C is now merged, so force the
    # absent state deterministically: `None` in sys.modules makes the import raise.
    saved = sys.modules.get("backend.phase2_demo")
    sys.modules["backend.phase2_demo"] = None  # type: ignore[assignment]
    try:
        assert _resolve_seed_and_run() is None
    finally:
        if saved is not None:
            sys.modules["backend.phase2_demo"] = saved
        else:
            del sys.modules["backend.phase2_demo"]


def test_seed_resolution_picks_up_int_c_when_present():
    async def seed_and_run(orch, events, *, tenant="dev-user", stop=None):
        return None

    fake = types.ModuleType("backend.phase2_demo")
    fake.seed_and_run = seed_and_run  # type: ignore[attr-defined]
    sys.modules["backend.phase2_demo"] = fake
    try:
        assert _resolve_seed_and_run() is seed_and_run
    finally:
        del sys.modules["backend.phase2_demo"]
