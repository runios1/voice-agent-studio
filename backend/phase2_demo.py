"""INT-C — demo scenario + live producers for the Phase-2 stack.

`backend/phase2_app.py` (INT-A) assembles ONE `OrchestratorService` + `EventService`
and serves them to the dashboard. On its own that stack is inert: a seeded campaign
sits still and the audit log never ticks. This module supplies the *motion* — it
authorizes a campaign and then drives a realistic, never-ending call-lifecycle
sequence onto the SAME event stream the browser is watching, so the dashboard's
fleet, live trail and kill-switch have something to reflect.

Contract seam (`contracts/dashboard_http/README.md` §4c). INT-A calls the frozen
entrypoint if this module is importable and falls back to a minimal inline seed if
not, so INT-C never blocks INT-A:

    async def seed_and_run(orch, events, *, tenant="dev-user", stop=None) -> None

Design choices:
  * We share the passed-in `orch`/`events` — NEVER build our own — so a control
    action from the dashboard (pause) and a produced call event land in the one log
    (that is the whole point of the assembly seam).
  * Call-lifecycle events go straight through `events.emit(type, **kwargs)` (the
    validate/persist/publish door). Campaign lifecycle transitions go through
    `orch.*` (authorize/autopause/resume) which emit through the orchestrator's own
    sink — wired to the same `events` by INT-A — so both halves interleave correctly.
  * Every payload is built to satisfy `backend/events/payloads.py` (the compliance-
    critical events carry their REQUIRED audit fields), so nothing is rejected at the
    emit boundary.
  * The loop is a bounded, repeating *script* gated on `stop`: one pass emits a known
    set of events (incl. exactly one `campaign.autopaused` + a `campaign.resumed` so
    the fleet visibly flips state and keeps moving), which makes it deterministically
    unit-testable with no HTTP.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Optional

from contracts.events.schema import EventType, Severity
from backend.events.payloads import LeadOutcome
from backend.orchestrator.service import LeadSpec

if TYPE_CHECKING:  # avoid hard import cycles; these are only type hints
    from backend.events.service import EventService
    from backend.orchestrator.service import OrchestratorService


# The demo agent. INT-A's stub `ConfigSource` returns a default `AgentConfig` for any
# agent_id, so this id only needs to be stable, not registered.
DEMO_AGENT_ID = "demo-sdr-agent"
DEMO_CAMPAIGN_NAME = "Q3 Outbound — West Coast leads"

# Pacing (seconds). Small enough to feel live in the browser, overridable so tests
# run in microseconds.
DEFAULT_BEAT_SECONDS = 1.5


@dataclass(frozen=True)
class _LeadScript:
    """One lead's scripted call outcome for a demo pass."""

    name: str
    phone: str
    outcome: LeadOutcome
    books_slot: bool


# A believable spread of outcomes so the dashboard shows more than one color.
_LEAD_SCRIPTS: list[_LeadScript] = [
    _LeadScript("Dana Whitfield", "+14155550101", LeadOutcome.QUALIFIED, books_slot=True),
    _LeadScript("Marcus Reyes", "+14155550102", LeadOutcome.NOT_QUALIFIED, books_slot=False),
    _LeadScript("Priya Nair", "+14155550103", LeadOutcome.NO_ANSWER, books_slot=False),
    _LeadScript("Sam Okafor", "+14155550104", LeadOutcome.CALLBACK_REQUESTED, books_slot=False),
    _LeadScript("Elena Sokolova", "+14155550105", LeadOutcome.QUALIFIED, books_slot=True),
]

_DISCLOSURE_TEXT = (
    "Hi, this is an AI assistant calling on behalf of Northwind Solar — "
    "just so you know you're speaking with an automated agent."
)


async def seed_and_run(
    orch: "OrchestratorService",
    events: "EventService",
    *,
    tenant: str = "dev-user",
    stop: Optional[asyncio.Event] = None,
    beat_seconds: float = DEFAULT_BEAT_SECONDS,
) -> None:
    """Authorize a demo campaign and drive live call motion until `stop` is set.

    Shares the passed-in `orch`/`events`. Returns cleanly when `stop` is set (or when
    it runs a single pass, if no `stop` is provided — so a caller can't hang forever
    by accident)."""
    # Whether the caller owns a stop it intends to set later ("run until stopped") vs.
    # no stop at all ("one pass, then terminate"). INT-A always passes its own Event.
    single_pass = stop is None
    stop = stop or asyncio.Event()

    campaign = await orch.authorize_campaign(
        tenant_id=tenant,
        agent_id=DEMO_AGENT_ID,
        authorized_by="demo-operator@voice-agent-studio",
        leads=[LeadSpec(phone=s.phone, display_name=s.name) for s in _LEAD_SCRIPTS],
        name=DEMO_CAMPAIGN_NAME,
    )

    # Repeat the demo pass until asked to stop. `single_pass` (no stop provided) runs
    # exactly one pass so the function always terminates on its own.
    cycle = 0
    while not stop.is_set():
        await _run_pass(orch, events, campaign.id, tenant, cycle, stop, beat_seconds)
        cycle += 1
        if single_pass:
            break


async def _run_pass(
    orch: "OrchestratorService",
    events: "EventService",
    campaign_id: str,
    tenant: str,
    cycle: int,
    stop: asyncio.Event,
    beat_seconds: float,
) -> None:
    """One full pass: dial every scripted lead, then trip + clear an auto-pause so the
    fleet visibly flips PAUSED (critical) → RUNNING and motion continues."""
    leads = orch.list_leads(campaign_id, tenant)
    # `list_leads` returns in insert order, aligned with `_LEAD_SCRIPTS`.
    for lead, script in zip(leads, _LEAD_SCRIPTS):
        if stop.is_set():
            return
        await _run_call(events, campaign_id, tenant, lead.id, script, cycle, stop, beat_seconds)

    if stop.is_set():
        return

    # Simulate a trip pattern P2-6 would detect (a burst of guardrail trips), then
    # exercise the kill switch on the shared orchestrator so the dashboard sees the
    # campaign self-pause and recover.
    await _emit(
        events, EventType.GUARDRAIL_TRIPPED, tenant,
        severity=Severity.WARNING,
        payload={"guardrail": "out_of_range_promise",
                 "detail": "agent hinted at a discount above the authorized cap"},
        campaign_id=campaign_id, agent_id=DEMO_AGENT_ID,
    )
    await _beat(stop, beat_seconds)

    await orch.autopause(
        campaign_id, tenant,
        reason="out_of_range_promise trip pattern (2 in 60s)",
    )
    await _beat(stop, beat_seconds)

    # An operator reviews and resumes; guard against a global emergency-stop being in
    # effect (resume would raise) so the demo self-heals instead of crashing.
    try:
        orch_state = orch.get_campaign(campaign_id, tenant).state
        if orch_state.value == "paused":
            await orch.resume(campaign_id, tenant)
    except Exception:
        # A real stop the dashboard triggered — leave it paused; the loop's `stop`
        # check (or a later resume) handles the rest.
        pass
    await _beat(stop, beat_seconds)


async def _run_call(
    events: "EventService",
    campaign_id: str,
    tenant: str,
    lead_id: str,
    script: _LeadScript,
    cycle: int,
    stop: asyncio.Event,
    beat_seconds: float,
) -> None:
    """Emit one lead's full call lifecycle in order, pausing a beat between events."""
    call_id = f"call_{lead_id}_{cycle}"
    corr = dict(campaign_id=campaign_id, lead_id=lead_id, call_id=call_id, agent_id=DEMO_AGENT_ID)

    await _emit(events, EventType.CALL_STARTED, tenant,
                payload={"to_number": script.phone, "direction": "outbound"}, **corr)
    await _beat(stop, beat_seconds)

    # Compliance-critical: AI disclosure spoken (REQUIRED `text`).
    await _emit(events, EventType.DISCLOSURE_SPOKEN, tenant,
                payload={"disclosed": True, "text": _DISCLOSURE_TEXT}, **corr)
    if stop.is_set():
        return
    await _beat(stop, beat_seconds)

    if script.outcome in (LeadOutcome.NO_ANSWER, LeadOutcome.VOICEMAIL):
        # A lead that never picked up: no tool work, just end the call.
        await _emit(events, EventType.LEAD_OUTCOME, tenant,
                    payload={"outcome": script.outcome.value}, **corr)
        await _beat(stop, beat_seconds)
        await _emit(events, EventType.CALL_ENDED, tenant,
                    payload={"duration_seconds": 8.0, "ended_reason": script.outcome.value}, **corr)
        return

    # A live conversation: the agent checks the calendar (tool), maybe books.
    await _emit(events, EventType.TOOL_INVOKED, tenant,
                payload={"tool_name": "check_calendar", "params": {"window": "next_7_days"},
                         "result_status": "ok"}, **corr)
    await _beat(stop, beat_seconds)

    if script.books_slot:
        slot_start = _iso_soon(days=2)
        await _emit(events, EventType.TOOL_INVOKED, tenant,
                    payload={"tool_name": "book_slot",
                             "params": {"slot_start": slot_start}, "result_status": "ok"}, **corr)
        await _beat(stop, beat_seconds)
        await _emit(events, EventType.SLOT_BOOKED, tenant,
                    payload={"slot_start": slot_start, "calendar_id": "primary"}, **corr)
        await _beat(stop, beat_seconds)

    await _emit(events, EventType.LEAD_OUTCOME, tenant,
                payload={"outcome": script.outcome.value}, **corr)
    await _beat(stop, beat_seconds)

    await _emit(events, EventType.CALL_ENDED, tenant,
                payload={"duration_seconds": 143.0, "ended_reason": "completed"}, **corr)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
async def _emit(events: "EventService", type: EventType, tenant: str,
                *, severity: Severity = Severity.INFO, payload: dict, **corr) -> None:
    await events.emit(type, tenant_id=tenant, payload=payload, severity=severity, **corr)


async def _beat(stop: asyncio.Event, beat_seconds: float) -> None:
    """Sleep one demo beat, but return the moment `stop` is set (so shutdown is
    prompt and tests with `beat_seconds=0` don't busy-spin the event loop)."""
    if beat_seconds <= 0:
        await asyncio.sleep(0)  # yield without pacing (tests)
        return
    try:
        await asyncio.wait_for(stop.wait(), timeout=beat_seconds)
    except asyncio.TimeoutError:
        return


def _iso_soon(*, days: int) -> str:
    from datetime import datetime, timezone

    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat()
