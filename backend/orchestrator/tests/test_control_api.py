"""The FastAPI control surface for the dashboard (P2-7) + tenant isolation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend.orchestrator.clock import ManualClock
from backend.orchestrator.control_api import create_app
from backend.orchestrator.events import InMemoryEventSink
from backend.orchestrator.mocks import InMemoryConfigSource, ScriptedDialer
from backend.orchestrator.repository import InMemoryOrchestratorRepository
from backend.orchestrator.service import OrchestratorService
from backend.orchestrator.tests.conftest import AGENT_ID, OTHER, TENANT, make_config

ALICE = {"X-User-Id": TENANT}
BOB = {"X-User-Id": OTHER}


@pytest.fixture
def client() -> TestClient:
    cfg = InMemoryConfigSource()
    cfg.add(TENANT, make_config())
    service = OrchestratorService(
        config_source=cfg,
        dialer=ScriptedDialer(),
        repo=InMemoryOrchestratorRepository(),
        sink=InMemoryEventSink(),
        clock=ManualClock(datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)),
    )
    return TestClient(create_app(service))


def _authorize(client, headers=ALICE, n=2):
    body = {
        "agent_id": AGENT_ID,
        "leads": [{"phone": f"+1555{i:04d}"} for i in range(n)],
        "name": "Q3 outbound",
    }
    return client.post("/campaigns", json=body, headers=headers)


def test_authorize_and_read(client):
    r = _authorize(client)
    assert r.status_code == 200
    cid = r.json()["id"]
    assert r.json()["state"] == "running"

    assert client.get("/campaigns", headers=ALICE).json()[0]["id"] == cid
    assert client.get(f"/campaigns/{cid}", headers=ALICE).json()["name"] == "Q3 outbound"
    assert len(client.get(f"/campaigns/{cid}/leads", headers=ALICE).json()) == 2


def test_pause_resume_autopause(client):
    cid = _authorize(client).json()["id"]

    assert client.post(f"/campaigns/{cid}/pause", headers=ALICE).json()["state"] == "paused"
    assert client.post(f"/campaigns/{cid}/resume", headers=ALICE).json()["state"] == "running"

    r = client.post(f"/campaigns/{cid}/autopause", json={"reason": "anomaly"}, headers=ALICE)
    assert r.json()["state"] == "paused"
    assert r.json()["autopause_reason"] == "anomaly"


def test_emergency_stop_pauses_running_campaigns(client):
    cid = _authorize(client).json()["id"]
    assert client.post("/emergency-stop", headers=ALICE).json()["stopped"] is True
    assert client.get(f"/campaigns/{cid}", headers=ALICE).json()["state"] == "paused"
    # Resume is refused until the stop is cleared.
    assert client.post(f"/campaigns/{cid}/resume", headers=ALICE).status_code == 409
    client.post("/emergency-stop/clear", headers=ALICE)
    assert client.post(f"/campaigns/{cid}/resume", headers=ALICE).status_code == 200


def test_tenant_isolation(client):
    cid = _authorize(client, headers=ALICE).json()["id"]
    # Bob cannot see or control Alice's campaign — it reads as absent (404), not leaked.
    assert client.get(f"/campaigns/{cid}", headers=BOB).status_code == 404
    assert client.post(f"/campaigns/{cid}/pause", headers=BOB).status_code == 404
    assert client.get("/campaigns", headers=BOB).json() == []


def test_missing_auth_is_rejected(client):
    assert _authorize(client, headers={}).status_code == 404


def test_authorize_unknown_agent_404(client):
    body = {"agent_id": "nope", "leads": [{"phone": "+15550000"}]}
    assert client.post("/campaigns", json=body, headers=ALICE).status_code == 404
