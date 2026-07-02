"""Versioning, revert, and optimistic concurrency."""

from __future__ import annotations

import pytest

from backend.config_gate.errors import ErrorKind, GateError
from backend.config_gate.tests.conftest import USER


def test_version_bumps_on_each_accepted_patch(service, agent_id):
    assert service.get_agent(agent_id, USER).meta.version == 1
    out = service.apply_patch(agent_id, USER, "conversation.persona.tone", "warm")
    assert out.config.meta.version == 2
    out = service.apply_patch(agent_id, USER, "conversation.persona.role", "SDR")
    assert out.config.meta.version == 3


def test_rejected_patch_does_not_bump_version(service, agent_id):
    with pytest.raises(GateError):
        service.apply_patch(agent_id, USER, "conversation.disclosure.must_disclose_ai", False)
    assert service.get_agent(agent_id, USER).meta.version == 1


def test_history_lists_all_versions(service, agent_id):
    service.apply_patch(agent_id, USER, "conversation.persona.tone", "warm")
    service.apply_patch(agent_id, USER, "conversation.persona.role", "SDR")
    versions = [v.version for v in service.history(agent_id, USER)]
    assert versions == [1, 2, 3]


def test_revert_restores_prior_content_as_new_version(service, agent_id):
    service.apply_patch(agent_id, USER, "conversation.persona.tone", "warm")   # v2
    service.apply_patch(agent_id, USER, "conversation.persona.tone", "brusque")  # v3
    reverted = service.revert(agent_id, USER, 2)
    assert reverted.conversation.persona.tone == "warm"
    assert reverted.meta.version == 4  # append-only history
    assert [v.version for v in service.history(agent_id, USER)] == [1, 2, 3, 4]


def test_revert_unknown_version_raises_not_found(service, agent_id):
    with pytest.raises(GateError) as ei:
        service.revert(agent_id, USER, 99)
    assert ei.value.kind == ErrorKind.NOT_FOUND


def test_optimistic_concurrency_conflict(service, agent_id):
    # Two clients load v1; the first write wins, the second (stale) is rejected.
    service.apply_patch(agent_id, USER, "conversation.persona.tone", "warm", expected_version=1)
    with pytest.raises(GateError) as ei:
        service.apply_patch(agent_id, USER, "conversation.persona.role", "SDR", expected_version=1)
    assert ei.value.kind == ErrorKind.CONFLICT


def test_omitted_expected_version_is_last_write_wins(service, agent_id):
    # Without expected_version the contract's plain {path,value} still works.
    service.apply_patch(agent_id, USER, "conversation.persona.tone", "warm")
    out = service.apply_patch(agent_id, USER, "conversation.persona.role", "SDR")
    assert out.config.meta.version == 3
