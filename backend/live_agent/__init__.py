"""backend/live_agent — the Live-native conversational agent (Phase 4).

This package implements the frozen `contracts/live_agent` interfaces:
`compiler.py` (P4-1, config -> `LiveAgentSpec`) and `moderation.py` (P4-3, the
`StreamModerator` that screens Live's output transcription as the net around the
agent's speech).
"""

from __future__ import annotations
