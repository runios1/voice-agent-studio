"""The dispatch loop — claims leads, delegates each dial, records the outcome.

This is the bounded-autonomy engine (P2-D1): given a RUNNING campaign it dials leads
unsupervised within the envelope, and stops launching NEW dials the instant the kill
switch flips (P2-D3) while letting in-flight calls finish. Every gate below is a
"before we start a new call" check, which is exactly why "stop new / finish live"
falls out for free.

Order of gates each tick (all cheap, all re-read from the DB so state is authoritative):
  1. kill switch — campaign not RUNNING, or a global emergency stop → stop launching.
  2. completion  — nothing left eligible or in flight → mark COMPLETED.
  3. calling hours — outside the window → sleep until it opens.
  4. concurrency — at `max_concurrent_calls` → wait for a call to finish.
  5. rate limit  — over `calls_per_minute` → wait for a slot.
  6. claim + dial — atomically claim one lead and launch its call.

Time is injected (`clock` + `sleep`) so a test drives a whole campaign — windows,
backoff, retries — with zero real waiting and zero flakiness.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Awaitable, Callable, Optional

from contracts.campaign.model import (
    Campaign,
    CampaignState,
    GuardrailEnvelope,
    Lead,
    LeadState,
)
from contracts.config_schema.schema import AgentConfig
from contracts.events.schema import EventType, Severity
from contracts.voice_runtime.interface import CallOutcome
from backend.orchestrator.clock import Clock, SystemClock
from backend.orchestrator.dialer import Dialer
from backend.orchestrator.events import EventSink, campaign_event, lead_event
from backend.orchestrator.repository import OrchestratorRepository
from backend.orchestrator.scheduling import RateLimiter, Scheduler

# Outcomes that end the lead for good — including OPTED_OUT, which must NEVER be
# retried (honoring the DNC opt-out is a locked guardrail).
_TERMINAL = {
    CallOutcome.BOOKED: "booked",
    CallOutcome.QUALIFIED: "qualified",
    CallOutcome.NOT_QUALIFIED: "not_qualified",
    CallOutcome.OPTED_OUT: "opted_out",
    CallOutcome.TRANSFERRED: "transferred",
}
# Outcomes that warrant another attempt if the envelope's cap isn't reached yet.
_RETRIABLE = {CallOutcome.NO_ANSWER, CallOutcome.VOICEMAIL, CallOutcome.FAILED}


def resolve_outcome(
    lead: Lead, outcome: CallOutcome, envelope: GuardrailEnvelope, scheduler: Scheduler
) -> Lead:
    """Apply a call outcome to the (already-dialed) lead: terminal, or a scheduled retry.

    `lead.attempts` was incremented at claim time, so the cap check here is against the
    attempts already made. Returns the same lead, mutated (caller persists it)."""
    if outcome in _TERMINAL:
        lead.state = LeadState.DONE
        lead.outcome = _TERMINAL[outcome]
        lead.next_action_at = None
        return lead

    # retriable (no-answer / voicemail / failed)
    if lead.attempts < envelope.max_attempts_per_lead:
        lead.state = LeadState.RETRY
        lead.outcome = outcome.value
        lead.next_action_at = scheduler.next_action_at(lead.attempts, envelope)
    else:
        lead.state = LeadState.DONE
        lead.outcome = f"exhausted_{outcome.value}"
        lead.next_action_at = None
    return lead


class CampaignRunner:
    """Runs ONE campaign to a terminal condition (completed, paused, or stopped).

    Crash-safe: `run` first re-drives any leads left mid-call by a previous process
    (recovery), then enters the dispatch loop. Because a resumed dial reuses the
    lead's `last_call_id`, an idempotent runtime returns the recorded outcome instead
    of dialing again — no double-dial (P2-D2)."""

    def __init__(
        self,
        repo: OrchestratorRepository,
        dialer: Dialer,
        sink: EventSink,
        config: AgentConfig,
        clock: Optional[Clock] = None,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
    ):
        self.repo = repo
        self.dialer = dialer
        self.sink = sink
        self.config = config
        self.clock = clock or SystemClock()
        self.scheduler = Scheduler(self.clock)
        self._sleep = sleep or asyncio.sleep
        self._tasks: set[asyncio.Task] = set()

    async def run(self, campaign_id: str, tenant_id: str) -> Campaign:
        campaign = self.repo.get_campaign(campaign_id, tenant_id)
        if campaign is None:
            raise KeyError(campaign_id)
        limiter = RateLimiter(campaign.envelope.calls_per_minute, self.clock)

        # --- recovery: resume anything a previous process left mid-call ----------
        for lead in self.repo.list_interrupted(campaign_id):
            self._launch(campaign, lead, limiter, record_dial=False)

        # --- dispatch loop -------------------------------------------------------
        while True:
            campaign = self.repo.get_campaign(campaign_id, tenant_id)
            assert campaign is not None
            env = campaign.envelope

            # 1. kill switch — stop launching new dials, let in-flight finish.
            if campaign.state != CampaignState.RUNNING or self.repo.is_globally_stopped(
                tenant_id
            ):
                break

            # 2. completion — idle with every lead terminal.
            if not self._tasks and not self.repo.has_unfinished(campaign_id):
                campaign = self._mark_completed(campaign)
                break

            now = self.clock.now()

            # 3. calling hours — outside the window, let any live call finish, else
            #    sleep until the window opens.
            if not self.scheduler.within_calling_hours(now, env):
                if self._tasks:
                    await self._wait_one()
                else:
                    opens = self.scheduler.next_window_open(now, env)
                    await self._sleep(max(0.0, (opens - now).total_seconds()))
                continue

            # 4. concurrency — wait for a call to finish if at the cap.
            if len(self._tasks) >= env.max_concurrent_calls:
                await self._wait_one()
                continue

            # 5. rate limit — wait for a free slot.
            wait = limiter.seconds_until_free()
            if wait > 0:
                await self._sleep(wait)
                continue

            # 6. claim + dial one eligible lead.
            lead = self.repo.claim_next_lead(campaign_id, now)
            if lead is not None:
                self._launch(campaign, lead, limiter, record_dial=True)
                continue

            # Nothing eligible right now: drain an in-flight call, else sleep to the
            # next scheduled retry (or bail if there is nothing left to wait for).
            if self._tasks:
                await self._wait_one()
                continue
            nxt = self._earliest_future(campaign_id, tenant_id, now)
            if nxt is None:
                break  # unfinished but nothing schedulable — avoid an infinite spin
            await self._sleep(max(0.0, (nxt - now).total_seconds()))

        # Let every in-flight call finish gracefully before returning (P2-D3).
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        return self.repo.get_campaign(campaign_id, tenant_id) or campaign

    # --- internals -----------------------------------------------------------
    def _launch(
        self, campaign: Campaign, lead: Lead, limiter: RateLimiter, record_dial: bool
    ) -> None:
        if record_dial:
            limiter.record_dial()
        task = asyncio.ensure_future(self._handle_lead(campaign, lead))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _wait_one(self) -> None:
        if not self._tasks:
            return
        done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            self._tasks.discard(t)

    async def _handle_lead(self, campaign: Campaign, lead: Lead) -> None:
        """Dial one already-claimed lead, then record its outcome durably."""
        try:
            session = await self.dialer.dial(self.config, campaign, lead)
            outcome = session.outcome or CallOutcome.FAILED
            if session.call_id:
                lead.last_call_id = session.call_id
        except asyncio.CancelledError:
            raise  # a "crash": leave the lead DIALING for recovery, don't record.
        except Exception:
            outcome = CallOutcome.FAILED

        resolve_outcome(lead, outcome, campaign.envelope, self.scheduler)
        self.repo.save_lead(lead)
        await self.sink.emit(
            lead_event(
                campaign,
                lead,
                EventType.LEAD_OUTCOME,
                self.clock,
                severity=Severity.INFO,
                payload={
                    "outcome": lead.outcome,
                    "state": lead.state.value,
                    "attempts": lead.attempts,
                    "call_outcome": outcome.value,
                },
            )
        )

    def _mark_completed(self, campaign: Campaign) -> Campaign:
        campaign.state = CampaignState.COMPLETED
        campaign.updated_at = self.clock.now()
        return self.repo.save_campaign(campaign)

    def _earliest_future(
        self, campaign_id: str, tenant_id: str, now: datetime
    ) -> Optional[datetime]:
        times = [
            l.next_action_at
            for l in self.repo.list_leads(campaign_id, tenant_id)
            if l.state in (LeadState.QUEUED, LeadState.RETRY)
            and l.next_action_at is not None
            and l.next_action_at > now
        ]
        return min(times) if times else None
