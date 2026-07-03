"""backend/live_agent — the Live-native conversational agent (Phase 4).

This package implements the frozen `contracts/live_agent` interfaces: `compiler.py`
(P4-1, config -> `LiveAgentSpec`), `moderation.py` (P4-3, the `StreamModerator` that
screens Live's output transcription as the net around the agent's speech), and
`session.py` (P4-2, `GeminiLiveAgentSession` — the runtime that connects one
conversation to Live and drives it, per `contracts/live_agent.LiveAgentSession`).
"""

from __future__ import annotations
