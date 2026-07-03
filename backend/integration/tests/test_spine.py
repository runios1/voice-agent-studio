"""The spine, end-to-end across the real seams — the test that proves the merged
workstreams actually compose into a working product.

A human authorizes a campaign; nothing else is touched. We then assert the WHOLE chain
fired on its own:

    SupervisedOrchestrator (auto-run)  ->  RealDialer  ->  real CallEngine
      ->  REAL ToolStack registry (build_registry + CalendarHandler)  ->  book_meeting
      ->  lead reaches DONE/booked  ->  the append-only event log tells the full story.

Only two things are faked, and only because they cost money / need a phone: the LLM (a
scripted wrapper that speaks then calls the `calendar` tool) and the phone medium
(`MockVoiceTransport`). Every seam BETWEEN them is the real code the product ships.
"""

from __future__ import annotations

import pytest

from contracts.config_schema.schema import AgentConfig
from contracts.campaign.model import LeadState
from contracts.events.schema import EventType

from backend.config_gate.service import AgentService
from backend.config_gate.repository import InMemoryConfigRepository

from backend.orchestrator.events import InMemoryEventSink
from backend.orchestrator.service import LeadSpec

from backend.voice_runtime.engine import CallEngine
from backend.voice_runtime.mocks import ScriptedToolWrapper, tool_call
from backend.voice_runtime.fixtures import config_with_calendar

from backend.integration.config_source import AgentServiceConfigSource
from backend.integration.dialer import RealDialer
from backend.integration.runtime import ToolStack
from backend.integration.supervisor import SupervisedOrchestrator

from backend.tool_registry.connections import ConnectionStore
from backend.tool_registry.credentials import EncryptedCredentialStore, generate_key
from backend.tool_registry.integrations import MockCalendarClient, MockEmailClient


TENANT = "dev-user"
AGENT_ID = "agent-under-test"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _script_wrapper() -> ScriptedToolWrapper:
    # opening turn (disclosure + opening), then book the slot, then close.
    return ScriptedToolWrapper([
        "Hi, quick call from Acme — is now an okay moment?",
        tool_call("calendar", start_iso="2026-07-10T10:00:00"),
        "Perfect, you're booked. Talk soon!",
    ])


def _tool_stack() -> ToolStack:
    stack = ToolStack(
        connections=ConnectionStore(),
        credentials=EncryptedCredentialStore(key=generate_key()),
        calendar_client=MockCalendarClient(),
        email_client=MockEmailClient(),
    )
    # Real OAuth would create these; seed a placeholder so the mock client has a token.
    stack.ensure_dev_connections(TENANT)
    return stack


def _config_source() -> AgentServiceConfigSource:
    """A real AgentServiceConfigSource over a real repo holding a calendar-enabled agent —
    so the orchestrator loads the SAME config object the builder would have produced."""
    repo = InMemoryConfigRepository()
    service = AgentService(repo)
    config: AgentConfig = config_with_calendar(agent_id=AGENT_ID)
    config.meta.owner_user_id = TENANT
    repo.create(config)
    return AgentServiceConfigSource(service)


@pytest.mark.anyio
async def test_authorize_drives_a_real_call_to_booked_with_full_event_trail():
    sink = InMemoryEventSink()
    stack = _tool_stack()
    engine = CallEngine(_script_wrapper(), sink)
    dialer = RealDialer(engine, stack, _StubFactory(), sink)
    orch = SupervisedOrchestrator(
        config_source=_config_source(), dialer=dialer, sink=sink
    )

    campaign = await orch.authorize_campaign(
        tenant_id=TENANT,
        agent_id=AGENT_ID,
        authorized_by=TENANT,
        leads=[LeadSpec(phone="+15550100", display_name="Ada Lovelace")],
        name="Spine test",
    )

    # The human only authorized — the loop ran itself. Drain it deterministically.
    await orch.wait_for(campaign.id)

    # 1) the lead was driven to a terminal, booked state (no double-dial).
    leads = orch.list_leads(campaign.id, TENANT)
    assert len(leads) == 1
    assert leads[0].state == LeadState.DONE
    assert leads[0].outcome == "booked"
    assert leads[0].attempts == 1

    # 2) the append-only event log tells the whole story across every seam.
    types = sink.types()
    assert EventType.CAMPAIGN_STARTED in types
    assert EventType.CALL_STARTED in types
    assert EventType.DISCLOSURE_SPOKEN in types   # mandatory AI disclosure fired in-call
    assert EventType.TOOL_INVOKED in types        # the real registry ran the tool
    assert EventType.SLOT_BOOKED in types         # the real CalendarHandler booked
    assert EventType.LEAD_OUTCOME in types

    # 3) tenant is stamped on every event (D-security).
    assert all(e.tenant_id == TENANT for e in sink.events)


@pytest.mark.anyio
async def test_unknown_agent_is_refused_not_leaked():
    orch = SupervisedOrchestrator(
        config_source=_config_source(),
        dialer=RealDialer(CallEngine(_script_wrapper(), InMemoryEventSink()), _tool_stack(), _StubFactory(), InMemoryEventSink()),
        sink=InMemoryEventSink(),
    )
    with pytest.raises(Exception):
        await orch.authorize_campaign(
            tenant_id=TENANT,
            agent_id="does-not-exist",
            authorized_by=TENANT,
            leads=[LeadSpec(phone="+15550100")],
            name="nope",
        )


class _StubFactory:
    """Transport factory that hands each dial a scripted mock voice leg (no phone)."""

    def create(self, lead):
        from backend.voice_runtime.transports import MockVoiceTransport

        return MockVoiceTransport(["Yes, Friday at ten works."])
