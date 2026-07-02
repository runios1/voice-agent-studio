"""Workstream 4 — Runtime loop (the chat that EXECUTES a config).

Phase 1 = text preview (D12): reads a config's `conversation` section and behaves
as that agent. Critical guardrails are enforced HERE in code (not as prompt text an
injected persona could override) — see `guardrails.py`. The prompt compiler
(`compiler.py`) orders LOCKED platform guardrails ABOVE user persona text and never
feeds `wishlist` items as instructions.

The loop is a piece you keep: in Phase 2 the text I/O is swapped for the voice Live
API and the in-call function layer (`tools.py`) grows real handlers. The seams here
are shaped for that.
"""

from backend.runtime_loop.compiler import compile_system_prompt
from backend.runtime_loop.engine import RuntimeEngine, TurnEvent
from backend.runtime_loop.session import PreviewSession, SessionStore

__all__ = [
    "compile_system_prompt",
    "RuntimeEngine",
    "TurnEvent",
    "PreviewSession",
    "SessionStore",
]
