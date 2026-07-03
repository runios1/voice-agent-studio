"""What a rule produces when a pattern trips: a `Signal`.

A Signal is the engine's internal currency — a rule detects a pattern and returns
a Signal describing WHAT to do (auto-pause vs escalate), for WHICH campaign, and
WHY. The engine, not the rule, decides whether to act (cooldown/debounce) and how
(kill switch, event emit, escalator)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from contracts.events.schema import Severity


class Action(str, Enum):
    AUTOPAUSE = "autopause"  # trip the orchestrator kill switch (P2-2) + emit event
    ESCALATE = "escalate"    # route a human notification via the escalator port


@dataclass(frozen=True)
class Signal:
    action: Action
    tenant_id: str
    campaign_id: str
    rule: str          # which rule fired (goes into the audit payload / logs)
    reason: str        # human-readable, surfaced on the dashboard + Campaign.autopause_reason
    severity: Severity
