"""Fixture Leads + configs for the voice-runtime tests and demo.

Reuses the Phase-1 `sample_ready_config` (the same honest SDR config the runtime loop
tests use) and layers on the Phase-2 pieces P2-1 needs: a `Lead` (from the frozen
campaign model) and a variant config with calendar automation ENABLED so the in-call
`book_meeting` tool actually materializes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.campaign.model import Lead
from contracts.config_schema.schema import AgentConfig

from backend.runtime_loop.fixtures import sample_ready_config


def sample_lead(
    *, campaign_id: str = "camp-1", tenant_id: str = "tenant-1", phone: str = "+15551234567"
) -> Lead:
    return Lead(
        id="lead-1",
        campaign_id=campaign_id,
        tenant_id=tenant_id,
        phone=phone,
        display_name="Jordan Rivera",
    )


def config_with_calendar(*, agent_id: str = "agent-1") -> AgentConfig:
    """The ready SDR config with calendar automation enabled — so an IN_CALL
    `book_meeting` tool is exposed. Everything else matches Phase 1."""
    config = sample_ready_config(agent_id=agent_id)
    config.automation.calendar.enabled = True
    config.automation.calendar.calendar_ref = "primary"
    return config


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
