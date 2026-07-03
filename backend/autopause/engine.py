"""AutoPauseEngine — the P2-6 consumer.

Reads the event stream one event at a time (read-only), runs each event past the
rule chain, and for every un-suppressed signal it *acts*:

  * AUTOPAUSE → trip P2-2's kill switch, then emit `campaign.autopaused` to P2-5.
  * ESCALATE  → route a human notification via the escalator port.

Debounce/cooldown (per campaign + action, on event-time) stops a noisy signal from
thrashing a campaign, and a `campaign.resumed` event clears the cooldown so a
restarted campaign can trip again. The engine never blocks in-flight calls — it
flips the kill switch and lets the orchestrator drain live calls (P2-D3)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from contracts.events.schema import Event, EventType, Severity

from .config import EngineConfig
from .ports import Escalator, EventSink, KillSwitch
from .rules import Rule, build_default_rules
from .signals import Action, Signal


class AutoPauseEngine:
    def __init__(
        self,
        *,
        config: EngineConfig | None = None,
        kill_switch: KillSwitch,
        event_sink: EventSink,
        escalator: Escalator,
        rules: list[Rule] | None = None,
    ) -> None:
        self.config = config or EngineConfig.default()
        self._kill_switch = kill_switch
        self._event_sink = event_sink
        self._escalator = escalator
        self._rules = rules if rules is not None else build_default_rules(self.config)
        # (action, tenant_id, campaign_id) -> event-time of last action taken.
        self._last_action: dict[tuple[Action, str, str], object] = {}

    # -- live wiring -------------------------------------------------------

    def attach(self, stream) -> None:
        """Subscribe to a live event stream (P2-5). The stream is expected to call
        our `handle` for each event via a `subscribe(callback)` method — matched by
        the in-memory mock and, at integration, by the real bus adapter."""
        stream.subscribe(self.handle)

    # -- core --------------------------------------------------------------

    def handle(self, event: Event) -> list[Signal]:
        """Process one event. Returns the signals that were *acted on* (post-cooldown)
        — handy for tests and for a caller that wants to log what fired."""
        # A resume re-arms detection for this campaign.
        if event.type is EventType.CAMPAIGN_RESUMED and event.campaign_id:
            self._clear_cooldowns(event.tenant_id, event.campaign_id)
            return []

        acted: list[Signal] = []
        for rule in self._rules:
            signal = rule.observe(event)
            if signal is None:
                continue
            if self._suppressed(signal, event):
                continue
            self._act(signal, event)
            self._last_action[self._cooldown_key(signal)] = event.occurred_at
            acted.append(signal)
        return acted

    # -- cooldown ----------------------------------------------------------

    @staticmethod
    def _cooldown_key(signal: Signal) -> tuple[Action, str, str]:
        return (signal.action, signal.tenant_id, signal.campaign_id)

    def _cooldown_for(self, action: Action) -> float:
        if action is Action.AUTOPAUSE:
            return self.config.autopause_cooldown_seconds
        return self.config.escalation_cooldown_seconds

    def _suppressed(self, signal: Signal, event: Event) -> bool:
        last = self._last_action.get(self._cooldown_key(signal))
        if last is None:
            return False
        window = timedelta(seconds=self._cooldown_for(signal.action))
        return (event.occurred_at - last) < window

    def _clear_cooldowns(self, tenant_id: str, campaign_id: str) -> None:
        for action in Action:
            self._last_action.pop((action, tenant_id, campaign_id), None)

    # -- acting ------------------------------------------------------------

    def _act(self, signal: Signal, trigger: Event) -> None:
        if signal.action is Action.AUTOPAUSE:
            self._kill_switch.pause_campaign(
                campaign_id=signal.campaign_id,
                tenant_id=signal.tenant_id,
                reason=signal.reason,
            )
            self._event_sink.emit(self._autopaused_event(signal, trigger))
        else:  # ESCALATE
            self._escalator.escalate(signal)

    def _autopaused_event(self, signal: Signal, trigger: Event) -> Event:
        """The `campaign.autopaused` event fed back to the single source of truth.
        Timestamped with the triggering event's time so the audit log reads
        deterministically on replay; carries the rule + the id of the event that
        tipped it over for traceability."""
        return Event(
            event_id=str(uuid.uuid4()),
            type=EventType.CAMPAIGN_AUTOPAUSED,
            occurred_at=trigger.occurred_at,
            severity=Severity.CRITICAL,
            tenant_id=signal.tenant_id,
            campaign_id=signal.campaign_id,
            agent_id=trigger.agent_id,
            payload={
                "rule": signal.rule,
                "reason": signal.reason,
                "triggered_by_event_id": trigger.event_id,
                "triggered_by_type": trigger.type.value,
            },
        )
