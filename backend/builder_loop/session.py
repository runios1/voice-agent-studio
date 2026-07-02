"""Builder conversation state.

Phase 1 keeps this in memory behind a Protocol (WS3 grill decision) so a
Postgres-backed store drops in later without touching the loop. The store holds the
running chat history for an agent's builder session; the config itself lives in the
gate, not here (the builder never owns config state).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from contracts.model_wrapper.interface import Message


@dataclass
class BuilderSession:
    agent_id: str
    history: list[Message] = field(default_factory=list)


class SessionStore(Protocol):
    def load(self, agent_id: str) -> BuilderSession: ...

    def save(self, session: BuilderSession) -> None: ...


class InMemorySessionStore:
    """Phase-1 default. Not durable; swap for a Postgres impl behind SessionStore."""

    def __init__(self) -> None:
        self._sessions: dict[str, BuilderSession] = {}

    def load(self, agent_id: str) -> BuilderSession:
        return self._sessions.setdefault(agent_id, BuilderSession(agent_id=agent_id))

    def save(self, session: BuilderSession) -> None:
        self._sessions[session.agent_id] = session
