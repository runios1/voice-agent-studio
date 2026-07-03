"""Persistence — the DB is the source of truth (P2-D2), and the leads table IS the queue.

There is no external broker. A "queue" that must survive a crash and never double-dial
is exactly a table of per-lead rows with a `state` + `next_action_at`; the dispatch
primitive is an **atomic claim** that flips one eligible lead `QUEUED/RETRY -> DIALING`
so no two workers can ever grab the same lead-attempt. In Postgres that claim is
`SELECT ... FOR UPDATE SKIP LOCKED`; in memory it's a lock. Everything the runner
needs (eligibility, in-flight counts, interrupted leads for recovery) is a query here.

Same shape as `config_gate.repository` (Protocol + InMemory for CI + Postgres for
prod): tenant isolation is enforced *in code* on every read — a campaign that isn't
yours reads as absent, never leaked (D-security). Stored models are deep-copied in
and out so a caller can't mutate persisted state by holding a reference.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime
from typing import Optional, Protocol

from contracts.campaign.model import Campaign, CampaignState, Lead, LeadState

# States a worker may still act on (fresh or waiting on backoff).
_ELIGIBLE = (LeadState.QUEUED, LeadState.RETRY)
# States that mean "a dial is/was in progress" — counted for concurrency + recovery.
_IN_FLIGHT = (LeadState.DIALING, LeadState.IN_CALL)


class OrchestratorRepository(Protocol):
    # --- campaigns -----------------------------------------------------------
    def create_campaign(self, campaign: Campaign) -> Campaign: ...
    def get_campaign(self, campaign_id: str, tenant_id: str) -> Optional[Campaign]: ...
    def save_campaign(self, campaign: Campaign) -> Campaign: ...
    def list_campaigns(self, tenant_id: str) -> list[Campaign]: ...

    # --- leads ---------------------------------------------------------------
    def add_leads(self, leads: list[Lead]) -> None: ...
    def get_lead(self, lead_id: str, tenant_id: str) -> Optional[Lead]: ...
    def save_lead(self, lead: Lead) -> Lead: ...
    def list_leads(self, campaign_id: str, tenant_id: str) -> list[Lead]: ...

    # --- the queue primitive -------------------------------------------------
    def claim_next_lead(self, campaign_id: str, now: datetime) -> Optional[Lead]: ...
    def count_in_flight(self, campaign_id: str) -> int: ...
    def list_interrupted(self, campaign_id: str) -> list[Lead]: ...
    def has_unfinished(self, campaign_id: str) -> bool: ...

    # --- global emergency stop ----------------------------------------------
    def set_global_stop(self, scope: str, stopped: bool) -> None: ...
    def is_globally_stopped(self, tenant_id: str) -> bool: ...


class InMemoryOrchestratorRepository:
    """Reference OrchestratorRepository. Tenant-scoped, lock-guarded claim."""

    GLOBAL_SCOPE = "*"

    def __init__(self) -> None:
        self._campaigns: dict[str, Campaign] = {}
        self._leads: dict[str, Lead] = {}
        self._global_stops: set[str] = set()
        # One lock guards the claim's read-modify-write so two concurrent workers
        # can never observe the same lead as eligible (the SKIP LOCKED analogue).
        self._lock = threading.Lock()

    # --- campaigns -----------------------------------------------------------
    def create_campaign(self, campaign: Campaign) -> Campaign:
        if campaign.id in self._campaigns:
            raise KeyError(f"campaign {campaign.id} already exists")
        self._campaigns[campaign.id] = copy.deepcopy(campaign)
        return copy.deepcopy(campaign)

    def get_campaign(self, campaign_id: str, tenant_id: str) -> Optional[Campaign]:
        c = self._campaigns.get(campaign_id)
        if c is None or c.tenant_id != tenant_id:
            return None  # missing OR not yours — indistinguishable on purpose
        return copy.deepcopy(c)

    def save_campaign(self, campaign: Campaign) -> Campaign:
        self._campaigns[campaign.id] = copy.deepcopy(campaign)
        return copy.deepcopy(campaign)

    def list_campaigns(self, tenant_id: str) -> list[Campaign]:
        return [copy.deepcopy(c) for c in self._campaigns.values() if c.tenant_id == tenant_id]

    # --- leads ---------------------------------------------------------------
    def add_leads(self, leads: list[Lead]) -> None:
        for lead in leads:
            self._leads[lead.id] = copy.deepcopy(lead)

    def get_lead(self, lead_id: str, tenant_id: str) -> Optional[Lead]:
        lead = self._leads.get(lead_id)
        if lead is None or lead.tenant_id != tenant_id:
            return None
        return copy.deepcopy(lead)

    def save_lead(self, lead: Lead) -> Lead:
        self._leads[lead.id] = copy.deepcopy(lead)
        return copy.deepcopy(lead)

    def list_leads(self, campaign_id: str, tenant_id: str) -> list[Lead]:
        return [
            copy.deepcopy(l)
            for l in self._leads.values()
            if l.campaign_id == campaign_id and l.tenant_id == tenant_id
        ]

    # --- the queue primitive -------------------------------------------------
    def _campaign_leads(self, campaign_id: str) -> list[Lead]:
        return [l for l in self._leads.values() if l.campaign_id == campaign_id]

    def claim_next_lead(self, campaign_id: str, now: datetime) -> Optional[Lead]:
        """Atomically flip one eligible lead to DIALING and return it (or None).

        Eligible = QUEUED/RETRY whose `next_action_at` has arrived. The claim
        increments `attempts` and stamps a deterministic `last_call_id` — the
        idempotency key the runtime honors — so exactly one dial is ever committed
        per lead-attempt, even under concurrency and even across a crash+resume.
        Calling-hours gating is the runner's job (campaign-global), not the claim's.
        """
        with self._lock:
            for lead in self._campaign_leads(campaign_id):
                if lead.state not in _ELIGIBLE:
                    continue
                if lead.next_action_at is not None and lead.next_action_at > now:
                    continue
                lead.attempts += 1
                lead.last_call_id = f"{lead.id}:{lead.attempts}"
                lead.state = LeadState.DIALING
                lead.next_action_at = None
                self._leads[lead.id] = lead
                return copy.deepcopy(lead)
        return None

    def count_in_flight(self, campaign_id: str) -> int:
        return sum(1 for l in self._campaign_leads(campaign_id) if l.state in _IN_FLIGHT)

    def list_interrupted(self, campaign_id: str) -> list[Lead]:
        return [
            copy.deepcopy(l) for l in self._campaign_leads(campaign_id) if l.state in _IN_FLIGHT
        ]

    def has_unfinished(self, campaign_id: str) -> bool:
        return any(l.state != LeadState.DONE for l in self._campaign_leads(campaign_id))

    # --- global emergency stop ----------------------------------------------
    def set_global_stop(self, scope: str, stopped: bool) -> None:
        if stopped:
            self._global_stops.add(scope)
        else:
            self._global_stops.discard(scope)

    def is_globally_stopped(self, tenant_id: str) -> bool:
        return self.GLOBAL_SCOPE in self._global_stops or tenant_id in self._global_stops
