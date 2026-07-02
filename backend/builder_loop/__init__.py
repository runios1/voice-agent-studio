"""Workstream 3 — the Builder loop (chat that EDITS the config).

A goal-seeking interviewer (D11/D12): it converses toward the completeness model,
emits config changes as structured tool-calls (patches, not regeneration — D5),
runs the four-way triage on volunteered detail (D13), and routes EVERY patch
through the config gate (the security boundary — D-security). It never writes the
config directly.

Public surface:
  * BuilderLoop.run_turn(agent_id, user_text) -> async stream of BuilderEvents
    (token / patch / notice), matching the SSE shape in contracts/api.
"""

from __future__ import annotations

from .events import BuilderEvent, NoticeEvent, PatchEvent, TokenEvent
from .gate import Gate, GateAccepted, GateError, Patch
from .loop import BuilderLoop
from .session import BuilderSession, InMemorySessionStore, SessionStore

__all__ = [
    "BuilderLoop",
    "BuilderEvent",
    "TokenEvent",
    "PatchEvent",
    "NoticeEvent",
    "Gate",
    "GateAccepted",
    "GateError",
    "Patch",
    "SessionStore",
    "InMemorySessionStore",
    "BuilderSession",
]
