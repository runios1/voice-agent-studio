"""SQLiteOrchestratorRepository — same `OrchestratorRepository` Protocol as
`InMemoryOrchestratorRepository`; focuses on what's specific to the SQLite impl:
the atomic claim, tenant isolation, and durability across a reopen."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.campaign.model import Campaign, Lead, LeadState
from backend.orchestrator.sqlite_repository import SQLiteOrchestratorRepository

NOW = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)


def _campaign(id="c1", tenant="tenant-alice") -> Campaign:
    return Campaign(id=id, tenant_id=tenant, agent_id="agent-1", created_at=NOW, updated_at=NOW)


def _lead(id, campaign_id="c1", tenant="tenant-alice", **kw) -> Lead:
    return Lead(id=id, campaign_id=campaign_id, tenant_id=tenant, phone="+15550000000", **kw)


@pytest.fixture
def repo(tmp_path) -> SQLiteOrchestratorRepository:
    return SQLiteOrchestratorRepository(str(tmp_path / "orch.db"))


def test_create_and_get_campaign(repo):
    repo.create_campaign(_campaign())
    assert repo.get_campaign("c1", "tenant-alice").agent_id == "agent-1"


def test_get_campaign_scoped_to_tenant(repo):
    repo.create_campaign(_campaign())
    assert repo.get_campaign("c1", "tenant-bob") is None  # missing OR not yours


def test_list_campaigns_scoped_to_tenant(repo):
    repo.create_campaign(_campaign("c1", "tenant-alice"))
    repo.create_campaign(_campaign("c2", "tenant-bob"))
    assert [c.id for c in repo.list_campaigns("tenant-alice")] == ["c1"]


def test_save_campaign_updates_fields(repo):
    c = repo.create_campaign(_campaign())
    c.name = "Renamed"
    repo.save_campaign(c)
    assert repo.get_campaign("c1", "tenant-alice").name == "Renamed"


def test_add_and_list_leads(repo):
    repo.create_campaign(_campaign())
    repo.add_leads([_lead("l1"), _lead("l2")])
    assert {l.id for l in repo.list_leads("c1", "tenant-alice")} == {"l1", "l2"}


def test_get_lead_scoped_to_tenant(repo):
    repo.create_campaign(_campaign())
    repo.add_leads([_lead("l1")])
    assert repo.get_lead("l1", "tenant-bob") is None


def test_claim_next_lead_flips_state_and_stamps_call_id(repo):
    repo.create_campaign(_campaign())
    repo.add_leads([_lead("l1")])
    claimed = repo.claim_next_lead("c1", NOW)
    assert claimed.id == "l1"
    assert claimed.state == LeadState.DIALING
    assert claimed.attempts == 1
    assert claimed.last_call_id == "l1:1"


def test_claim_next_lead_skips_ineligible_and_future_leads(repo):
    repo.create_campaign(_campaign())
    repo.add_leads(
        [
            _lead("done", state=LeadState.DONE),
            _lead("future", next_action_at=datetime(2099, 1, 1, tzinfo=timezone.utc)),
            _lead("ready"),
        ]
    )
    claimed = repo.claim_next_lead("c1", NOW)
    assert claimed.id == "ready"


def test_claim_next_lead_returns_none_when_nothing_eligible(repo):
    repo.create_campaign(_campaign())
    repo.add_leads([_lead("done", state=LeadState.DONE)])
    assert repo.claim_next_lead("c1", NOW) is None


def test_count_in_flight_and_list_interrupted(repo):
    repo.create_campaign(_campaign())
    repo.add_leads([_lead("l1")])
    repo.claim_next_lead("c1", NOW)
    assert repo.count_in_flight("c1") == 1
    assert [l.id for l in repo.list_interrupted("c1")] == ["l1"]


def test_has_unfinished(repo):
    repo.create_campaign(_campaign())
    repo.add_leads([_lead("l1")])
    assert repo.has_unfinished("c1") is True
    lead = repo.get_lead("l1", "tenant-alice")
    lead.state = LeadState.DONE
    repo.save_lead(lead)
    assert repo.has_unfinished("c1") is False


def test_global_stop_scopes(repo):
    assert repo.is_globally_stopped("tenant-alice") is False
    repo.set_global_stop("tenant-alice", True)
    assert repo.is_globally_stopped("tenant-alice") is True
    assert repo.is_globally_stopped("tenant-bob") is False
    repo.set_global_stop(repo.GLOBAL_SCOPE, True)
    assert repo.is_globally_stopped("tenant-bob") is True
    repo.set_global_stop("tenant-alice", False)
    assert repo.is_globally_stopped("tenant-alice") is True  # global scope still stops it


def test_persists_across_reopen(tmp_path):
    path = str(tmp_path / "orch.db")
    first = SQLiteOrchestratorRepository(path)
    first.create_campaign(_campaign())
    first.add_leads([_lead("l1")])

    reopened = SQLiteOrchestratorRepository(path)
    assert reopened.get_campaign("c1", "tenant-alice") is not None
    assert reopened.get_lead("l1", "tenant-alice") is not None
