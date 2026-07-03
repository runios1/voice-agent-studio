"""Crash-resume with no double-dial (P2-D2), and the atomic claim under concurrency."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone

from contracts.campaign.model import (
    Campaign,
    CampaignState,
    GuardrailEnvelope,
    Lead,
    LeadState,
)
from backend.orchestrator.mocks import ScriptedDialer
from backend.orchestrator.runner import CampaignRunner
from backend.orchestrator.repository import InMemoryOrchestratorRepository
from backend.orchestrator.tests.conftest import (
    AGENT_ID,
    TENANT,
    await_state,
    leads,
    make_config,
)


async def test_resume_after_dial_completed_but_unrecorded_does_not_redial(
    service, repo, config_source, clock
):
    """Crash between the call returning and its outcome being saved. On resume the
    lead is re-driven with the SAME last_call_id → the idempotent runtime returns the
    recorded outcome instead of dialing again."""
    d = ScriptedDialer()
    campaign = await service.authorize_campaign(
        tenant_id=TENANT, agent_id=AGENT_ID, authorized_by="alice", leads=leads(1),
    )
    config = config_source.get_config(AGENT_ID, TENANT)

    # Simulate: claim + dial happened (dialer recorded it) but the process died before
    # save_lead — so the row is still DIALING.
    lead = repo.claim_next_lead(campaign.id, clock.now())
    session = await d.dial(config, campaign, lead)
    assert len(d.dialed) == 1
    assert repo.get_lead(lead.id, TENANT).state == LeadState.DIALING  # unrecorded

    # Restart: a fresh runner over the same repo + same (idempotent) dialer.
    runner = CampaignRunner(repo, d, service.sink, config, clock=clock, sleep=service._sleep)
    await runner.run(campaign.id, TENANT)

    assert len(d.dialed) == 1  # NOT re-dialed
    assert repo.get_lead(lead.id, TENANT).state == LeadState.DONE
    assert repo.get_campaign(campaign.id, TENANT).state == CampaignState.COMPLETED


async def test_resume_after_crash_mid_call_dials_once(
    repo, sink, config_source, clock, fast_sleep
):
    """Hard crash while a call was in flight (never completed). Resume places the call
    exactly once and finishes the campaign."""
    d = ScriptedDialer()
    config = config_source.get_config(AGENT_ID, TENANT)
    now = clock.now()
    campaign = Campaign(
        id="camp-x", tenant_id=TENANT, agent_id=AGENT_ID, state=CampaignState.RUNNING,
        envelope=GuardrailEnvelope(max_concurrent_calls=1, calls_per_minute=1000),
        created_at=now, updated_at=now,
    )
    repo.create_campaign(campaign)
    lead_rows = [
        Lead(id=f"l{i}", campaign_id="camp-x", tenant_id=TENANT, phone=f"+1{i}") for i in range(2)
    ]
    repo.add_leads(lead_rows)
    d._hang = {"l0"}

    runner = CampaignRunner(repo, d, sink, config, clock=clock, sleep=fast_sleep)
    run_task = asyncio.ensure_future(runner.run("camp-x", TENANT))
    await await_state(repo, "l0", TENANT, LeadState.DIALING)

    # Crash: kill the loop AND every in-flight call task.
    run_task.cancel()
    for t in list(runner._tasks):
        t.cancel()
    await asyncio.gather(run_task, *runner._tasks, return_exceptions=True)
    assert len(d.dialed) == 0                       # the hung call never actually placed
    assert repo.get_lead("l0", TENANT).state == LeadState.DIALING

    # Restart and let the previously-hung call go through.
    d.release.set()
    runner2 = CampaignRunner(repo, d, sink, config, clock=clock, sleep=fast_sleep)
    await runner2.run("camp-x", TENANT)

    assert d.dialed.count("l0:1") == 1              # exactly one dial for the interrupted lead
    assert len(d.dialed) == 2                       # l0 + l1, once each
    assert all(l.state == LeadState.DONE for l in repo.list_leads("camp-x", TENANT))
    assert repo.get_campaign("camp-x", TENANT).state == CampaignState.COMPLETED


def test_claim_is_atomic_under_threads():
    """Many workers hammering claim never grab the same lead twice (the SKIP LOCKED
    analogue). Every lead is claimed exactly once."""
    repo = InMemoryOrchestratorRepository()
    now = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    repo.create_campaign(
        Campaign(id="c", tenant_id=TENANT, agent_id=AGENT_ID, state=CampaignState.RUNNING,
                 created_at=now, updated_at=now)
    )
    n = 200
    repo.add_leads(
        [Lead(id=f"l{i}", campaign_id="c", tenant_id=TENANT, phone=f"+1{i}") for i in range(n)]
    )

    claimed: list[str] = []
    guard = threading.Lock()

    def worker():
        while True:
            lead = repo.claim_next_lead("c", now)
            if lead is None:
                return
            with guard:
                claimed.append(lead.id)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed) == n
    assert len(set(claimed)) == n  # no lead claimed twice
