"""Detection rules over the event stream.

Each rule is a small, independent detector: it `observe`s one event at a time,
holds only its own window state, and returns a `Signal` when its pattern trips
(else None). The engine owns cooldown/debounce and the actual acting — a rule
never touches the kill switch. Adding a new detection pattern = adding a rule
class + a config section; the engine loop is untouched.

v1 ruleset (README: guardrail-trip count + anomaly heuristics + escalation):
  * GuardrailTripRule    — N `guardrail.tripped` in a window  → AUTOPAUSE
  * CriticalGuardrailRule— one CRITICAL `guardrail.tripped`   → AUTOPAUSE (now)
  * EscalationSpikeRule  — M `call.escalated` in a window     → ESCALATE
"""

from __future__ import annotations

from typing import Optional, Protocol

from contracts.events.schema import Event, EventType, Severity

from .config import (
    CriticalGuardrailConfig,
    EngineConfig,
    EscalationSpikeConfig,
    GuardrailTripConfig,
)
from .signals import Action, Signal
from .windows import SlidingWindow


class Rule(Protocol):
    name: str

    def observe(self, event: Event) -> Optional[Signal]: ...


def _scope_key(event: Event) -> tuple[str, str]:
    return (event.tenant_id, event.campaign_id or "")


class GuardrailTripRule:
    """Auto-pause when a campaign accumulates `threshold` guardrail trips inside
    the window — the core P2-6 pattern (README / P2-D3)."""

    name = "guardrail_trip_threshold"

    def __init__(self, cfg: GuardrailTripConfig) -> None:
        self._cfg = cfg
        self._window = SlidingWindow(cfg.window_seconds)

    def observe(self, event: Event) -> Optional[Signal]:
        if not self._cfg.enabled:
            return None
        if event.type is not EventType.GUARDRAIL_TRIPPED or not event.campaign_id:
            return None
        count = self._window.add(_scope_key(event), event.occurred_at)
        if count < self._cfg.threshold:
            return None
        return Signal(
            action=Action.AUTOPAUSE,
            tenant_id=event.tenant_id,
            campaign_id=event.campaign_id,
            rule=self.name,
            reason=(
                f"{count} guardrail trips within {int(self._cfg.window_seconds)}s "
                f"(threshold {self._cfg.threshold})"
            ),
            severity=Severity.CRITICAL,
        )


class CriticalGuardrailRule:
    """One CRITICAL guardrail trip is a compliance breach (undisclosed AI, DNC).
    Don't wait for a count — pause immediately."""

    name = "critical_guardrail"

    def __init__(self, cfg: CriticalGuardrailConfig) -> None:
        self._cfg = cfg

    def observe(self, event: Event) -> Optional[Signal]:
        if not self._cfg.enabled:
            return None
        if event.type is not EventType.GUARDRAIL_TRIPPED or not event.campaign_id:
            return None
        if event.severity is not Severity.CRITICAL:
            return None
        return Signal(
            action=Action.AUTOPAUSE,
            tenant_id=event.tenant_id,
            campaign_id=event.campaign_id,
            rule=self.name,
            reason="critical guardrail breach — immediate auto-pause",
            severity=Severity.CRITICAL,
        )


class EscalationSpikeRule:
    """A burst of warm-transfers in one campaign → page a human (not a pause)."""

    name = "escalation_spike"

    def __init__(self, cfg: EscalationSpikeConfig) -> None:
        self._cfg = cfg
        self._window = SlidingWindow(cfg.window_seconds)

    def observe(self, event: Event) -> Optional[Signal]:
        if not self._cfg.enabled:
            return None
        if event.type is not EventType.CALL_ESCALATED or not event.campaign_id:
            return None
        count = self._window.add(_scope_key(event), event.occurred_at)
        if count < self._cfg.threshold:
            return None
        return Signal(
            action=Action.ESCALATE,
            tenant_id=event.tenant_id,
            campaign_id=event.campaign_id,
            rule=self.name,
            reason=(
                f"{count} escalations within {int(self._cfg.window_seconds)}s "
                f"(threshold {self._cfg.threshold}) — campaign needs a human"
            ),
            severity=Severity.WARNING,
        )


def build_default_rules(config: EngineConfig) -> list[Rule]:
    """The v1 rule chain, in evaluation order."""
    return [
        CriticalGuardrailRule(config.critical_guardrail),
        GuardrailTripRule(config.guardrail_trip),
        EscalationSpikeRule(config.escalation_spike),
    ]
