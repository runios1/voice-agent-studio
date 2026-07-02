"""Preview session state — Phase 1 in-memory store.

A preview session holds the running message history for one text-preview
conversation, plus a `disclosed` flag so the hard AI-disclosure step fires exactly
once per session. This is ephemeral testing state, so it lives in-process; the
`SessionStore` interface is deliberately tiny so it can be swapped for Redis / a DB
later without touching the engine.

Not to be confused with persisted AgentConfig versions (that is WS2's domain). This
is transient conversation scratch state for the preview surface only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from contracts.model_wrapper.interface import Message


@dataclass
class PreviewSession:
    session_id: str
    agent_id: str
    messages: list[Message] = field(default_factory=list)
    disclosed: bool = False  # has the hard AI-disclosure step already fired?

    def add(self, role: str, content: str) -> None:
        self.messages.append(Message(role=role, content=content))


class SessionStore:
    """In-process session store keyed by session_id. Not thread-safe by design —
    Phase 1 preview is single-user-per-session; add locking if that changes."""

    def __init__(self) -> None:
        self._sessions: dict[str, PreviewSession] = {}

    def create(self, agent_id: str, session_id: str | None = None) -> PreviewSession:
        sid = session_id or uuid.uuid4().hex
        session = PreviewSession(session_id=sid, agent_id=agent_id)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> PreviewSession | None:
        return self._sessions.get(session_id)

    def get_or_create(self, agent_id: str, session_id: str | None = None) -> PreviewSession:
        if session_id is not None:
            existing = self._sessions.get(session_id)
            if existing is not None:
                return existing
        return self.create(agent_id, session_id)

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
