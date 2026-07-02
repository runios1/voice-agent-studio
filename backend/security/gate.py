"""
Free-text screening entry point for the config gate (Workstream 2).

WS2 owns the structural checks (schema/type validation, locked-path rejection,
tenant scoping). AFTER those pass, for any mutation whose value is free text, WS2
calls `screen_free_text(...)` and honours the returned `ScreenDecision`:

  * decision.blocked  -> reject the mutation; build the typed API error from
    `decision.error_kind` ("screening_blocked") + `decision.message`.
  * FLAG              -> apply the mutation, but surface `screening_flagged` as a
    conversational notice (accept-but-flag).
  * ACCEPT           -> apply normally.

This is the SAME policy the model-wrapper decorator uses (via engine.screen_text),
so a forged PATCH and a builder tool-call get identical treatment (D-security).
"""

from __future__ import annotations

from .config import ScreeningConfig
from .engine import screen_text
from .models import Direction, ScreenDecision
from .screener import Screener


async def screen_free_text(
    screener: Screener,
    path: str,
    value: str,
    *,
    config: ScreeningConfig | None = None,
) -> ScreenDecision:
    """Screen a single free-text field value bound for the config.

    `path` (e.g. "conversation.persona.tone") is used only as audit context — the
    gate has already decided the path is writable; screening judges the *content*.
    Values are treated as INBOUND (they become instructions a model will read).
    """
    return await screen_text(
        screener,
        value,
        Direction.INBOUND,
        config or ScreeningConfig.from_env(),
        context=f"gate:{path}",
    )
