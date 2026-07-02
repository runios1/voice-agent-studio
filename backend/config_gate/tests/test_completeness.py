"""Completeness model — DRAFT until every required field is satisfied, then READY."""

from __future__ import annotations

from contracts.config_schema.schema import AgentStatus
from backend.config_gate.completeness import evaluate_status, missing_required
from backend.config_gate.tests.conftest import READY_PATCHES, USER, drive_to_ready


def test_fresh_agent_is_draft(service, agent_id):
    config = service.get_agent(agent_id, USER)
    assert config.meta.status == AgentStatus.DRAFT
    assert evaluate_status(config) == AgentStatus.DRAFT


def test_missing_lists_the_unfilled_required_fields(service, agent_id):
    config = service.get_agent(agent_id, USER)
    missing = missing_required(config)
    # voicemail.action now defaults to None (undecided), so it is a genuine gap.
    assert "conversation.voicemail.action" in missing
    assert "conversation.persona.role" in missing
    assert "conversation.qualification.criteria" in missing


def test_status_flips_to_ready_when_all_required_satisfied(service, agent_id):
    drive_to_ready(service, agent_id)
    config = service.get_agent(agent_id, USER)
    assert config.meta.status == AgentStatus.READY
    assert missing_required(config) == []


def test_last_required_patch_is_what_flips_status(service, agent_id):
    # Apply all but the last required patch: still DRAFT.
    for path, value in READY_PATCHES[:-1]:
        out = service.apply_patch(agent_id, USER, path, value)
        assert out.config.meta.status == AgentStatus.DRAFT
    # The final one flips it.
    last_path, last_value = READY_PATCHES[-1]
    out = service.apply_patch(agent_id, USER, last_path, last_value)
    assert out.config.meta.status == AgentStatus.READY


def test_emptying_a_required_field_drops_back_to_draft(service, agent_id):
    drive_to_ready(service, agent_id)
    out = service.apply_patch(agent_id, USER, "conversation.qualification.criteria", [])
    assert out.config.meta.status == AgentStatus.DRAFT
