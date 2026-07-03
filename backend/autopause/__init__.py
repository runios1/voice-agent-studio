"""P2-6 — Auto-pause / escalation engine.

Read-only consumer of the event stream (contracts/events) that detects trip
patterns and, through narrow ports, invokes P2-2's kill switch + emits
`campaign.autopaused`, or routes a human escalation. See README.md for boundaries.
"""

from .config import (
    CriticalGuardrailConfig,
    EngineConfig,
    EscalationSpikeConfig,
    GuardrailTripConfig,
)
from .engine import AutoPauseEngine
from .ports import Escalator, EventSink, KillSwitch
from .rules import (
    CriticalGuardrailRule,
    EscalationSpikeRule,
    GuardrailTripRule,
    Rule,
    build_default_rules,
)
from .signals import Action, Signal

__all__ = [
    "AutoPauseEngine",
    "EngineConfig",
    "GuardrailTripConfig",
    "CriticalGuardrailConfig",
    "EscalationSpikeConfig",
    "Action",
    "Signal",
    "Rule",
    "build_default_rules",
    "GuardrailTripRule",
    "CriticalGuardrailRule",
    "EscalationSpikeRule",
    "KillSwitch",
    "EventSink",
    "Escalator",
]
