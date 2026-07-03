"""Kill switch (P2-D3): pause, global emergency stop, and the autopause hook each
halt NEW dials while letting the in-flight call finish."""

from __future__ import annotations

import asyncio

import pytest

from contracts.campaign.model import CampaignState, GuardrailEnvelope, LeadState
from contracts.events.schema import EventType, Severity
from backend.orchestrator.errors import IllegalTransition
from backend.orchestrator.mocks import ScriptedDialer
from backend.orchestrator.service import OrchestratorService
from backend.orchestrator.tests.conftest import AGENT_ID, TENANT, await_state, leads


async def _running_with_one_call_in_flight(repo, sink, config_source, clock, fast_sleep):
    """Authorize a 3-lead campaign (cap 1), start it, and block on the first live call."""
    campaign_leads = leads(3)
    d = ScriptedDialer()
    svc = OrchestratorService(
        config_source=config_source, dialer=d, repo=repo, sink=sink,
        clock=clock, sleep=fast_sleep,
    )
    campaign = await svc.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=campaign_leads,
        envelope=GuardrailEnvelope(max_concurrent_calls=1, calls_per_minute=1000),
    )
    first_lead = svc.list_leads(campaign.id, TENANT)[0].id
    d._hang = {first_lead}  # hang the first call so it stays in flight
    task = asyncio.ensure_future(svc.run_campaign(campaign.id, TENANT))
    await await_state(repo, first_lead, TENANT, LeadState.DIALING)
    return svc, d, campaign, first_lead, task


async def test_pause_halts_new_dials_and_lets_inflight_finish(
    repo, sink, config_source, clock, fast_sleep
):
    svc, d, campaign, first_lead, task = await _running_with_one_call_in_flight(
        repo, sink, config_source, clock, fast_sleep
    )

    await svc.pause(campaign.id, TENANT)   # kill switch
    d.release.set()                        # allow the live call to complete
    await task

    result = repo.get_campaign(campaign.id, TENANT)
    assert result.state == CampaignState.PAUSED
    rows = {l.id: l.state for l in repo.list_leads(campaign.id, TENANT)}
    assert rows[first_lead] == LeadState.DONE                 # in-flight finished
    queued = [s for s in rows.values() if s == LeadState.QUEUED]
    assert len(queued) == 2                                   # the other two never dialed
    assert len(d.dialed) == 1
    assert sink.of_type(EventType.CAMPAIGN_PAUSED)


async def test_global_emergency_stop_halts_campaign(
    repo, sink, config_source, clock, fast_sleep
):
    svc, d, campaign, first_lead, task = await _running_with_one_call_in_flight(
        repo, sink, config_source, clock, fast_sleep
    )

    await svc.emergency_stop(TENANT)
    d.release.set()
    await task

    result = repo.get_campaign(campaign.id, TENANT)
    assert result.state == CampaignState.PAUSED
    assert repo.is_globally_stopped(TENANT) is True
    assert len(d.dialed) == 1
    # A resume is refused while the global stop stands.
    with pytest.raises(IllegalTransition):
        await svc.resume(campaign.id, TENANT)


async def test_autopause_hook_trips_kill_switch_with_reason(
    repo, sink, config_source, clock, fast_sleep
):
    svc, d, campaign, first_lead, task = await _running_with_one_call_in_flight(
        repo, sink, config_source, clock, fast_sleep
    )

    await svc.autopause(campaign.id, TENANT, reason="3 guardrail trips in 60s")
    d.release.set()
    await task

    result = repo.get_campaign(campaign.id, TENANT)
    assert result.state == CampaignState.PAUSED
    assert result.autopause_reason == "3 guardrail trips in 60s"
    evts = sink.of_type(EventType.CAMPAIGN_AUTOPAUSED)
    assert evts and evts[0].severity == Severity.CRITICAL
    assert len(d.dialed) == 1


async def test_resume_continues_the_campaign(repo, sink, config_source, clock, fast_sleep):
    svc, d, campaign, first_lead, task = await _running_with_one_call_in_flight(
        repo, sink, config_source, clock, fast_sleep
    )
    await svc.pause(campaign.id, TENANT)
    d.release.set()
    await task
    assert repo.get_campaign(campaign.id, TENANT).state == CampaignState.PAUSED

    # Resume and drive the rest to completion.
    await svc.resume(campaign.id, TENANT)
    await svc.run_campaign(campaign.id, TENANT)

    result = repo.get_campaign(campaign.id, TENANT)
    assert result.state == CampaignState.COMPLETED
    assert all(l.state == LeadState.DONE for l in repo.list_leads(campaign.id, TENANT))
    assert len(d.dialed) == 3
