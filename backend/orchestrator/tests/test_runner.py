"""The dispatch loop: full drain, retries/backoff, exhaustion, hours, rate, concurrency."""

from __future__ import annotations

import asyncio

from contracts.campaign.model import CampaignState, GuardrailEnvelope, LeadState
from contracts.events.schema import EventType
from contracts.voice_runtime.interface import CallOutcome
from backend.orchestrator.mocks import ScriptedDialer
from backend.orchestrator.service import OrchestratorService
from backend.orchestrator.tests.conftest import (
    AGENT_ID,
    TENANT,
    await_state,
    leads,
    make_config,
)


async def _authorize(service, n, envelope=None):
    return await service.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice",
        leads=leads(n), envelope=envelope, name="Test",
    )


async def test_full_drain_dials_every_lead_once(service, repo, dialer, sink):
    campaign = await _authorize(service, 3)
    result = await service.run_campaign(campaign.id, TENANT)

    assert result.state == CampaignState.COMPLETED
    rows = repo.list_leads(campaign.id, TENANT)
    assert all(l.state == LeadState.DONE and l.outcome == "qualified" for l in rows)
    assert len(dialer.dialed) == 3                       # no double-dial
    assert len(sink.of_type(EventType.CAMPAIGN_STARTED)) == 1
    assert len(sink.of_type(EventType.LEAD_OUTCOME)) == 3


async def test_no_answer_then_success_retries_with_backoff(service, repo, config_source, clock):
    # A dialer that says no-answer on attempt 1, qualified on attempt 2.
    d = ScriptedDialer(outcomes={}, default=CallOutcome.QUALIFIED)
    lead_outcomes = {}
    svc = OrchestratorService(
        config_source=config_source, dialer=d, repo=repo, sink=service.sink,
        clock=clock, sleep=service._sleep,
    )
    campaign = await svc.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=leads(1),
    )
    lid = repo.list_leads(campaign.id, TENANT)[0].id
    d._outcomes[lid] = [CallOutcome.NO_ANSWER, CallOutcome.QUALIFIED]

    await svc.run_campaign(campaign.id, TENANT)

    lead = repo.get_lead(lid, TENANT)
    assert lead.state == LeadState.DONE
    assert lead.outcome == "qualified"
    assert lead.attempts == 2
    assert len(d.dialed) == 2  # two real dials, one per attempt


async def test_all_no_answer_exhausts_at_attempt_cap(service, repo, config_source, clock):
    d = ScriptedDialer(default=CallOutcome.NO_ANSWER)
    svc = OrchestratorService(
        config_source=config_source, dialer=d, repo=repo, sink=service.sink,
        clock=clock, sleep=service._sleep,
    )
    # Cap attempts at 2 (<= locked 3).
    env = GuardrailEnvelope(max_attempts_per_lead=2)
    campaign = await svc.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=leads(1), envelope=env,
    )
    lid = repo.list_leads(campaign.id, TENANT)[0].id

    await svc.run_campaign(campaign.id, TENANT)

    lead = repo.get_lead(lid, TENANT)
    assert lead.state == LeadState.DONE
    assert lead.attempts == 2
    assert lead.outcome == "exhausted_no_answer"
    assert len(d.dialed) == 2


async def test_opted_out_is_terminal_never_retried(service, repo, config_source, clock):
    d = ScriptedDialer(default=CallOutcome.OPTED_OUT)
    svc = OrchestratorService(
        config_source=config_source, dialer=d, repo=repo, sink=service.sink,
        clock=clock, sleep=service._sleep,
    )
    campaign = await svc.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=leads(1),
    )
    lid = repo.list_leads(campaign.id, TENANT)[0].id
    await svc.run_campaign(campaign.id, TENANT)

    lead = repo.get_lead(lid, TENANT)
    assert lead.state == LeadState.DONE and lead.outcome == "opted_out"
    assert lead.attempts == 1  # honored immediately, never dialed again


async def test_waits_for_calling_window_before_dialing(repo, sink, config_source, dialer):
    from backend.orchestrator.clock import ManualClock
    from datetime import datetime, timezone

    # Start at 06:00 — before the 08:00 window opens.
    clock = ManualClock(datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc))

    async def sleep(seconds):
        if seconds > 0:
            clock.advance(seconds)
        await asyncio.sleep(0)

    svc = OrchestratorService(
        config_source=config_source, dialer=dialer, repo=repo, sink=sink,
        clock=clock, sleep=sleep,
    )
    campaign = await svc.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=leads(1),
    )
    await svc.run_campaign(campaign.id, TENANT)

    assert clock.now().hour >= 8                 # it slept into the window
    assert len(dialer.dialed) == 1


async def test_rate_limit_spaces_dials(service, repo, dialer, clock):
    start = clock.now()
    env = GuardrailEnvelope(calls_per_minute=2, max_concurrent_calls=5)
    campaign = await _authorize(service, 5, envelope=env)
    await service.run_campaign(campaign.id, TENANT)

    assert len(dialer.dialed) == 5
    # 5 dials at 2/min => 2 @ t0, 2 @ t0+60, 1 @ t0+120: at least 120s must have passed.
    assert (clock.now() - start).total_seconds() >= 120


async def test_concurrency_cap_is_respected(service, repo):
    d = ScriptedDialer(hang_leads=set())  # will set below
    # Hang every lead so they stay in flight while we inspect.
    campaign = await service.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=leads(3),
        envelope=GuardrailEnvelope(max_concurrent_calls=2, calls_per_minute=1000),
    )
    lead_ids = [l.id for l in service.list_leads(campaign.id, TENANT)]
    service.dialer = ScriptedDialer(hang_leads=set(lead_ids))
    d = service.dialer

    task = asyncio.ensure_future(service.run_campaign(campaign.id, TENANT))
    # Wait until the cap is saturated.
    for _ in range(500):
        if repo.count_in_flight(campaign.id) == 2:
            break
        await asyncio.sleep(0)
    assert repo.count_in_flight(campaign.id) == 2          # never exceeds the cap
    dialing = [l for l in repo.list_leads(campaign.id, TENANT) if l.state == LeadState.DIALING]
    queued = [l for l in repo.list_leads(campaign.id, TENANT) if l.state == LeadState.QUEUED]
    assert len(dialing) == 2 and len(queued) == 1

    d.release.set()                                        # let them finish
    await task
    assert repo.get_campaign(campaign.id, TENANT).state == CampaignState.COMPLETED
