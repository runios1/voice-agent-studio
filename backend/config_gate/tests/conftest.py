"""Shared fixtures for the config-gate tests."""

from __future__ import annotations

import pytest

from backend.config_gate.repository import InMemoryConfigRepository
from backend.config_gate.service import AgentService

USER = "user-alice"
OTHER = "user-bob"

# The patches that, together, satisfy every required_for_ready field and flip an
# agent from DRAFT to READY. voicemail.action now defaults to None (undecided), so
# it is a genuine required field that must be set explicitly.
READY_PATCHES: list[tuple[str, object]] = [
    ("conversation.persona.role", "SDR for Acme"),
    ("conversation.persona.tone", "warm and concise"),
    ("conversation.opening", "Hi, this is Ada calling from Acme about your demo request."),
    ("conversation.primary_objective", "book a 15-minute discovery call"),
    ("conversation.qualification.criteria", [{"label": "Budget", "question": "What's the budget?"}]),
    ("conversation.voicemail.action", "hang_up"),
]


@pytest.fixture
def repo() -> InMemoryConfigRepository:
    return InMemoryConfigRepository()


@pytest.fixture
def service(repo: InMemoryConfigRepository) -> AgentService:
    return AgentService(repo)


@pytest.fixture
def agent_id(service: AgentService) -> str:
    return service.create_agent(USER, "Test agent").meta.id


def drive_to_ready(service: AgentService, agent_id: str, user: str = USER) -> None:
    for path, value in READY_PATCHES:
        service.apply_patch(agent_id, user, path, value)
