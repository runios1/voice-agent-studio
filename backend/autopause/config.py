"""Configurable thresholds/rules for the auto-pause engine.

Boundary rule (README): keep thresholds/rules configurable — no magic numbers
buried inline in the detection code. Every tunable lives here as a frozen
dataclass, and `EngineConfig.from_dict` lets a future caller load these from the
DB / env / a per-tenant policy without touching the engine.

Defaults are deliberately conservative for an autonomous dialer: a handful of
guardrail trips inside a few minutes is enough to warrant a human look, and a
single CRITICAL trip (a compliance breach — undisclosed AI, DNC violation) pauses
immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class GuardrailTripConfig:
    """N `guardrail.tripped` events for one campaign inside a sliding window."""

    enabled: bool = True
    threshold: int = 3
    window_seconds: float = 300.0  # 5 minutes


@dataclass(frozen=True)
class CriticalGuardrailConfig:
    """A single CRITICAL-severity `guardrail.tripped` — pause on the spot."""

    enabled: bool = True


@dataclass(frozen=True)
class EscalationSpikeConfig:
    """M `call.escalated` events for one campaign inside a window → page a human.

    A burst of warm-transfers (leads asking for a human / low-confidence agent)
    is a signal the campaign needs attention even when no guardrail tripped."""

    enabled: bool = True
    threshold: int = 3
    window_seconds: float = 300.0


@dataclass(frozen=True)
class EngineConfig:
    guardrail_trip: GuardrailTripConfig = field(default_factory=GuardrailTripConfig)
    critical_guardrail: CriticalGuardrailConfig = field(
        default_factory=CriticalGuardrailConfig
    )
    escalation_spike: EscalationSpikeConfig = field(default_factory=EscalationSpikeConfig)

    # Debounce: once we auto-pause / escalate a campaign, ignore the same action
    # for that campaign for this long (event-time). Cleared early by a
    # `campaign.resumed` event so a re-started campaign can trip again.
    autopause_cooldown_seconds: float = 900.0   # 15 minutes
    escalation_cooldown_seconds: float = 600.0  # 10 minutes

    @staticmethod
    def default() -> "EngineConfig":
        return EngineConfig()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EngineConfig":
        """Build a config from a plain dict (future: per-tenant policy in the DB).

        Unknown keys are ignored so a newer policy blob can't crash an older
        engine; known nested sections are merged over their defaults."""

        base = cls()
        nested = {
            "guardrail_trip": GuardrailTripConfig,
            "critical_guardrail": CriticalGuardrailConfig,
            "escalation_spike": EscalationSpikeConfig,
        }
        updates: dict[str, Any] = {}
        for name, klass in nested.items():
            if isinstance(data.get(name), dict):
                current = getattr(base, name)
                valid = {
                    k: v
                    for k, v in data[name].items()
                    if k in current.__dataclass_fields__
                }
                updates[name] = replace(current, **valid)
        for scalar in ("autopause_cooldown_seconds", "escalation_cooldown_seconds"):
            if scalar in data:
                updates[scalar] = data[scalar]
        return replace(base, **updates)
