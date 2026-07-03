"""End-to-end through the REAL dialer seam (VoiceRuntimeDialer -> frozen VoiceRuntime).

The other tests use `ScriptedDialer` for speed; this one drives the code path the
integrator keeps: the orchestrator builds a transport (P2-1 factory) + registry (P2-3)
and calls the frozen `VoiceRuntime.run_call`. It proves the seam and the full event
trail an authorized campaign produces (campaign.started -> call.started/ended per
lead -> lead.outcome), which is what the dashboard (P2-7) and audit log consume.
"""

from __future__ import annotations

from contracts.campaign.model import CampaignState, LeadState
from contracts.events.schema import EventType
from backend.orchestrator.dialer import VoiceRuntimeDialer
from backend.orchestrator.events import InMemoryEventSink
from backend.orchestrator.mocks import (
    InMemoryConfigSource,
    MockToolRegistry,
    MockTransportFactory,
    MockVoiceRuntime,
)
from backend.orchestrator.service import OrchestratorService
from backend.orchestrator.tests.conftest import AGENT_ID, TENANT, leads, make_config


async def test_campaign_through_voice_runtime_seam(repo, clock, fast_sleep):
    sink = InMemoryEventSink()
    config_source = InMemoryConfigSource()
    config_source.add(TENANT, make_config())

    # The real wiring: VoiceRuntime (mocked) + transport factory (P2-1) + registry (P2-3).
    runtime = MockVoiceRuntime(sink=sink, clock=clock)
    dialer = VoiceRuntimeDialer(runtime, MockTransportFactory(), MockToolRegistry())

    service = OrchestratorService(
        config_source=config_source, dialer=dialer, repo=repo, sink=sink,
        clock=clock, sleep=fast_sleep,
    )
    campaign = await service.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=leads(2),
    )
    result = await service.run_campaign(campaign.id, TENANT)

    assert result.state == CampaignState.COMPLETED
    assert all(l.state == LeadState.DONE for l in repo.list_leads(campaign.id, TENANT))
    assert len(runtime.dialed) == 2

    # The full event trail is on the stream, correctly correlated.
    types = sink.types()
    assert types.count(EventType.CAMPAIGN_STARTED) == 1
    assert types.count(EventType.CALL_STARTED) == 2
    assert types.count(EventType.CALL_ENDED) == 2
    assert types.count(EventType.LEAD_OUTCOME) == 2
    for e in sink.events:
        assert e.tenant_id == TENANT           # tenant always present (D-security)
        assert e.campaign_id == campaign.id
