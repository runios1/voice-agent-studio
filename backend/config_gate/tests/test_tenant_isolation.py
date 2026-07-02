"""Tenant isolation — enforced in code, never by a client-supplied identity."""

from __future__ import annotations

import pytest

from backend.config_gate.errors import ErrorKind, GateError
from backend.config_gate.tests.conftest import OTHER, USER


def test_other_user_cannot_read(service, agent_id):
    with pytest.raises(GateError) as ei:
        service.get_agent(agent_id, OTHER)
    assert ei.value.kind == ErrorKind.NOT_FOUND


def test_other_user_cannot_patch(service, agent_id):
    with pytest.raises(GateError) as ei:
        service.apply_patch(agent_id, OTHER, "conversation.persona.tone", "warm")
    assert ei.value.kind == ErrorKind.NOT_FOUND


def test_other_user_cannot_revert(service, agent_id):
    service.apply_patch(agent_id, USER, "conversation.persona.tone", "warm")
    with pytest.raises(GateError) as ei:
        service.revert(agent_id, OTHER, 1)
    assert ei.value.kind == ErrorKind.NOT_FOUND


def test_other_user_cannot_see_history(service, agent_id):
    with pytest.raises(GateError) as ei:
        service.history(agent_id, OTHER)
    assert ei.value.kind == ErrorKind.NOT_FOUND


def test_listing_is_scoped_per_owner(service):
    a = service.create_agent(USER, "Alice's agent").meta.id
    service.create_agent(OTHER, "Bob's agent")
    alice_ids = [m.id for m in service.list_agents(USER)]
    assert alice_ids == [a]
    assert all(m.owner_user_id == OTHER for m in service.list_agents(OTHER))
