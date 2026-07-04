"""OrchestratorService — authorize campaigns, drive them, and work the kill switch.

The public surface P2-1 (runs calls it dispatches), P2-6 (trips its kill switch), and
P2-7 (control API) depend on. It owns the state transitions and the events; the
per-lead dispatch mechanics live in `CampaignRunner`.

Kill switch (P2-D3) — ONE mechanism, `campaign.state == PAUSED`, reached three ways:
  * `pause`  — a human hits pause (manual).
  * `emergency_stop` — a global flag that halts every RUNNING campaign at once.
  * `autopause` — the hook P2-6 calls when a trip pattern fires.
All three stop NEW dials; in-flight calls finish (the runner's gate does this). None
of them touch a live call — hard-aborting a human call is itself a compliance risk.

The AgentConfig comes from a `ConfigSource` (config_gate at integration; mocked here)
because we need the LOCKED guardrails to clamp the authorized envelope (D4/D-security).
"""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable, Optional, Protocol

from pydantic import BaseModel

from contracts.campaign.model import (
    Campaign,
    CampaignState,
    GuardrailEnvelope,
    Lead,
    LeadState,
)
from contracts.config_schema.schema import AgentConfig
from contracts.events.schema import EventType, Severity
from backend.orchestrator.clock import Clock, SystemClock
from backend.orchestrator.dialer import Dialer
from backend.orchestrator.envelope import clamp_envelope
from backend.orchestrator.errors import IllegalTransition, NotFound
from backend.orchestrator.events import EventSink, campaign_event
from backend.orchestrator.repository import (
    InMemoryOrchestratorRepository,
    OrchestratorRepository,
)
from backend.orchestrator.runner import CampaignRunner


log = logging.getLogger("voice_agent_studio.orchestrator")


class LeadSpec(BaseModel):
    phone: str
    display_name: Optional[str] = None


class CallerIdVerifier(Protocol):
    """DEMO/trial support: register a lead number as a Twilio verified caller ID so a
    trial account is allowed to dial it. Returns the code Twilio speaks on its
    verification call, or None. Structurally satisfied by
    `live_agent.phone_transport.TwilioCallerIdVerifier`; the default no-ops so paid
    accounts, dev, and tests need nothing."""

    async def verify(self, phone: str, *, friendly_name: Optional[str] = None) -> Optional[str]: ...


class _NullCallerIdVerifier:
    async def verify(self, phone: str, *, friendly_name: Optional[str] = None) -> Optional[str]:
        return None


class ConfigSource(Protocol):
    """How the orchestrator loads a built AgentConfig. At integration this is backed
    by config_gate's tenant-scoped repository; here by an in-memory stub."""

    def get_config(self, agent_id: str, tenant_id: str) -> Optional[AgentConfig]: ...


class OrchestratorService:
    def __init__(
        self,
        config_source: ConfigSource,
        dialer: Dialer,
        repo: Optional[OrchestratorRepository] = None,
        sink: Optional[EventSink] = None,
        clock: Optional[Clock] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
        caller_id_verifier: Optional[CallerIdVerifier] = None,
    ):
        self.config_source = config_source
        self.dialer = dialer
        # DEMO: on a Twilio trial account, a lead must be a verified caller ID before it
        # can be dialed. The real verifier (injected at integration) kicks that flow off
        # as leads are registered; the no-op default is right for paid accounts + tests.
        self.caller_id_verifier = caller_id_verifier or _NullCallerIdVerifier()
        self.repo = repo or InMemoryOrchestratorRepository()
        # A no-op sink keeps the service usable without the event backbone; the real
        # P2-5 sink is injected at integration.
        self.sink = sink or _NullSink()
        self.clock = clock or SystemClock()
        self._sleep = sleep

    # --- authorize (P2-D1) ---------------------------------------------------
    async def authorize_campaign(
        self,
        tenant_id: str,
        agent_id: str,
        authorized_by: str,
        leads: list[LeadSpec],
        envelope: Optional[GuardrailEnvelope] = None,
        name: str = "Untitled campaign",
    ) -> Campaign:
        config = self.config_source.get_config(agent_id, tenant_id)
        if config is None:
            raise NotFound(agent_id)

        # The envelope may only ever be equal-or-stricter than the locked guardrails.
        safe_env = clamp_envelope(envelope or GuardrailEnvelope(), config)

        now = self.clock.now()
        campaign_id = f"camp_{uuid.uuid4().hex[:16]}"
        campaign = Campaign(
            id=campaign_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            state=CampaignState.RUNNING,
            envelope=safe_env,
            authorized_by=authorized_by,
            authorized_at=now,
            created_at=now,
            updated_at=now,
        )
        self.repo.create_campaign(campaign)

        lead_rows = [
            Lead(
                id=f"lead_{uuid.uuid4().hex[:16]}",
                campaign_id=campaign_id,
                tenant_id=tenant_id,
                phone=spec.phone,
                display_name=spec.display_name,
                state=LeadState.QUEUED,
            )
            for spec in leads
        ]
        self.repo.add_leads(lead_rows)
        await self._verify_caller_ids(lead_rows)

        await self._emit(
            campaign, EventType.CAMPAIGN_STARTED, payload={"lead_count": len(lead_rows)}
        )
        return campaign

    async def _verify_caller_ids(self, lead_rows: list[Lead]) -> None:
        """DEMO/trial support: as leads are registered, kick off Twilio's verified-caller-ID
        flow for each so a trial account is allowed to dial them (Twilio calls the number and
        speaks a code the callee enters — see `TwilioCallerIdVerifier`). Best-effort: a paid
        account uses the no-op verifier, and any failure here (already verified, trial cap
        hit, network) is logged, never raised — it must not block a campaign."""
        for lead in lead_rows:
            try:
                code = await self.caller_id_verifier.verify(
                    lead.phone, friendly_name=lead.display_name or "Lead"
                )
                if code is not None:
                    log.info(
                        "caller-id verification started for %s — Twilio is calling it to "
                        "speak code %s (the callee must answer and enter it)",
                        lead.phone,
                        code,
                    )
            except Exception as exc:  # noqa: BLE001 — demo helper must never break authorize
                log.warning("caller-id verification for %s failed (ignored): %s", lead.phone, exc)

    # --- run / recover -------------------------------------------------------
    async def run_campaign(self, campaign_id: str, tenant_id: str) -> Campaign:
        """Drive the campaign to a terminal condition. Re-entrant + crash-safe: the
        runner recovers any interrupted leads first, so calling this again after a
        restart resumes cleanly with no double-dial."""
        campaign = self._require(campaign_id, tenant_id)
        config = self.config_source.get_config(campaign.agent_id, tenant_id)
        if config is None:
            raise NotFound(campaign.agent_id)
        runner = CampaignRunner(
            self.repo, self.dialer, self.sink, config, clock=self.clock, sleep=self._sleep
        )
        return await runner.run(campaign_id, tenant_id)

    # --- kill switch (P2-D3) -------------------------------------------------
    async def pause(self, campaign_id: str, tenant_id: str) -> Campaign:
        return await self._transition_to_paused(
            campaign_id, tenant_id, EventType.CAMPAIGN_PAUSED, "manual", Severity.INFO
        )

    async def resume(self, campaign_id: str, tenant_id: str) -> Campaign:
        campaign = self._require(campaign_id, tenant_id)
        if self.repo.is_globally_stopped(tenant_id):
            raise IllegalTransition(
                "A global emergency stop is in effect — clear it before resuming.",
                campaign_id,
            )
        if campaign.state == CampaignState.RUNNING:
            return campaign
        if campaign.state != CampaignState.PAUSED:
            raise IllegalTransition(f"Cannot resume a {campaign.state.value} campaign.", campaign_id)
        campaign.state = CampaignState.RUNNING
        campaign.autopause_reason = None
        campaign.updated_at = self.clock.now()
        saved = self.repo.save_campaign(campaign)
        await self._emit(saved, EventType.CAMPAIGN_RESUMED)
        return saved

    async def autopause(self, campaign_id: str, tenant_id: str, reason: str) -> Campaign:
        """The hook P2-6 calls. Trips the kill switch and records WHY, CRITICAL-severity."""
        campaign = self._require(campaign_id, tenant_id)
        if campaign.state == CampaignState.COMPLETED:
            raise IllegalTransition("Campaign already completed.", campaign_id)
        campaign.state = CampaignState.PAUSED
        campaign.autopause_reason = reason
        campaign.updated_at = self.clock.now()
        saved = self.repo.save_campaign(campaign)
        await self._emit(
            saved, EventType.CAMPAIGN_AUTOPAUSED, severity=Severity.CRITICAL,
            payload={"reason": reason},
        )
        return saved

    async def emergency_stop(self, tenant_id: str, scope: Optional[str] = None) -> None:
        """Global stop: set the flag AND pause every RUNNING campaign in scope. New
        dials stop everywhere; in-flight calls finish."""
        flag_scope = scope or tenant_id
        self.repo.set_global_stop(flag_scope, True)
        for campaign in self.repo.list_campaigns(tenant_id):
            if campaign.state == CampaignState.RUNNING:
                campaign.state = CampaignState.PAUSED
                campaign.updated_at = self.clock.now()
                saved = self.repo.save_campaign(campaign)
                await self._emit(saved, EventType.CAMPAIGN_PAUSED, severity=Severity.CRITICAL,
                                 payload={"reason": "emergency_stop"})

    def clear_emergency_stop(self, tenant_id: str, scope: Optional[str] = None) -> None:
        self.repo.set_global_stop(scope or tenant_id, False)

    # --- reads (control API / dashboard) -------------------------------------
    def get_campaign(self, campaign_id: str, tenant_id: str) -> Campaign:
        return self._require(campaign_id, tenant_id)

    def list_campaigns(self, tenant_id: str) -> list[Campaign]:
        return self.repo.list_campaigns(tenant_id)

    def list_leads(self, campaign_id: str, tenant_id: str) -> list[Lead]:
        self._require(campaign_id, tenant_id)  # tenant check
        return self.repo.list_leads(campaign_id, tenant_id)

    # --- internals -----------------------------------------------------------
    def _require(self, campaign_id: str, tenant_id: str) -> Campaign:
        campaign = self.repo.get_campaign(campaign_id, tenant_id)
        if campaign is None:
            raise NotFound(campaign_id)
        return campaign

    async def _transition_to_paused(
        self,
        campaign_id: str,
        tenant_id: str,
        event: EventType,
        reason: str,
        severity: Severity,
    ) -> Campaign:
        campaign = self._require(campaign_id, tenant_id)
        if campaign.state == CampaignState.PAUSED:
            return campaign
        if campaign.state != CampaignState.RUNNING:
            raise IllegalTransition(f"Cannot pause a {campaign.state.value} campaign.", campaign_id)
        campaign.state = CampaignState.PAUSED
        campaign.updated_at = self.clock.now()
        saved = self.repo.save_campaign(campaign)
        await self._emit(saved, event, severity=severity, payload={"reason": reason})
        return saved

    async def _emit(
        self,
        campaign: Campaign,
        type: EventType,
        severity: Severity = Severity.INFO,
        payload: Optional[dict] = None,
    ) -> None:
        event = campaign_event(campaign, type, self.clock, severity=severity, payload=payload)
        await self.sink.emit(event)


class _NullSink:
    async def emit(self, event) -> None:  # noqa: D401 - no-op
        return None
