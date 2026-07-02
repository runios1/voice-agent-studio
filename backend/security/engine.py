"""
The one place that runs a screen end-to-end: screener -> policy -> audit log.

Both public surfaces call this:
  * the ModelWrapper decorator (decorator.py) — every model in/out;
  * the config-gate helper (gate.py) — every free-text mutation.

Keeping it here means the fail-open/fail-closed logic and the audit trail are
identical no matter which door content comes through (source-agnostic, D-security).
"""

from __future__ import annotations

from . import audit
from .config import ScreeningConfig
from .models import Decision, Direction, ScreenDecision, ScreenResult
from .policy import decide
from .screener import Screener


async def screen_text(
    screener: Screener,
    text: str,
    direction: Direction,
    config: ScreeningConfig,
    *,
    context: str = "",
) -> ScreenDecision:
    """Screen one string and return the policy decision. Never raises for content."""
    if not text or not text.strip():
        return ScreenDecision(decision=Decision.ACCEPT, direction=direction)

    try:
        result = await screener.screen(text, direction)
    except Exception as exc:  # a misbehaving screener must not crash the request
        audit.log_unavailable(direction, context=context, error=type(exc).__name__)
        result = ScreenResult(available=False)
    else:
        if not result.available:
            audit.log_unavailable(direction, context=context, error="unavailable")

    decision = decide(text, direction, result, config)
    audit.log_decision(decision, text, context=context)
    return decision
