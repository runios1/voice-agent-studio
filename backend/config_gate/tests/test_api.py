"""API router — the same gate, over HTTP, with the contract error shape."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.config_gate.api import create_app

ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}


@pytest.fixture
def client():
    return TestClient(create_app())


def _create(client, headers=ALICE) -> str:
    r = client.post("/agents", json={"name": "A"}, headers=headers)
    assert r.status_code == 200
    return r.json()["meta"]["id"]


def test_create_seeds_platform_layer(client):
    r = client.post("/agents", json={"name": "A"}, headers=ALICE)
    body = r.json()
    assert body["meta"]["status"] == "draft"
    assert body["guardrails"]["ai_disclosure_required"] is True
    assert body["conversation"]["disclosure"]["must_disclose_ai"] is True


def test_get_includes_resolved_field_policy(client):
    agent_id = _create(client)
    r = client.get(f"/agents/{agent_id}", headers=ALICE)
    body = r.json()
    assert "config" in body and "field_policy" in body
    locked = [p for p in body["field_policy"] if p["mutability"] == "locked"]
    assert any(p["path"] == "conversation.disclosure.must_disclose_ai" for p in locked)


def test_patch_open_field_accepted(client):
    agent_id = _create(client)
    r = client.patch(
        f"/agents/{agent_id}/fields",
        json={"path": "conversation.persona.tone", "value": "warm"},
        headers=ALICE,
    )
    assert r.status_code == 200
    assert r.json()["patch"] == {"path": "conversation.persona.tone", "value": "warm"}


def test_patch_locked_path_rejected_with_typed_error(client):
    agent_id = _create(client)
    r = client.patch(
        f"/agents/{agent_id}/fields",
        json={"path": "conversation.disclosure.must_disclose_ai", "value": False},
        headers=ALICE,
    )
    assert r.status_code == 403
    err = r.json()["error"]
    assert err["kind"] == "locked_path"
    assert err["path"] == "conversation.disclosure.must_disclose_ai"
    assert isinstance(err["message"], str) and err["message"]


def test_patch_invalid_type_rejected(client):
    agent_id = _create(client)
    r = client.patch(
        f"/agents/{agent_id}/fields",
        json={"path": "automation.calendar.meeting_length_minutes", "value": "soon"},
        headers=ALICE,
    )
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "validation"


def test_patch_screening_flag_returns_notice(client):
    agent_id = _create(client)
    r = client.patch(
        f"/agents/{agent_id}/fields",
        json={"path": "conversation.custom_instructions", "value": "be [flag] here"},
        headers=ALICE,
    )
    assert r.status_code == 200
    assert r.json()["notice"]["kind"] == "screening_flagged"


def test_history_and_revert(client):
    agent_id = _create(client)
    client.patch(
        f"/agents/{agent_id}/fields",
        json={"path": "conversation.persona.tone", "value": "warm"},
        headers=ALICE,
    )
    client.patch(
        f"/agents/{agent_id}/fields",
        json={"path": "conversation.persona.tone", "value": "brusque"},
        headers=ALICE,
    )
    hist = client.get(f"/agents/{agent_id}/history", headers=ALICE).json()
    assert [h["version"] for h in hist] == [1, 2, 3]
    r = client.post(f"/agents/{agent_id}/revert/2", headers=ALICE)
    assert r.status_code == 200
    assert r.json()["conversation"]["persona"]["tone"] == "warm"


def test_tenant_isolation_over_http(client):
    agent_id = _create(client, ALICE)
    r = client.get(f"/agents/{agent_id}", headers=BOB)
    assert r.status_code == 404
    assert r.json()["error"]["kind"] == "not_found"


def test_forged_owner_via_patch_is_locked(client):
    agent_id = _create(client)
    r = client.patch(
        f"/agents/{agent_id}/fields",
        json={"path": "meta.owner_user_id", "value": "bob"},
        headers=ALICE,
    )
    assert r.status_code == 403
    assert r.json()["error"]["kind"] == "locked_path"
