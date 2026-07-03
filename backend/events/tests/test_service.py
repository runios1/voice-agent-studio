"""EventService emit boundary — envelope defaults, validation, persist+publish."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.events.schema import EventType, Severity
from backend.events.errors import EventValidationError
from backend.events.store import EventQuery
from .conftest import TENANT


async def test_emit_fills_envelope_defaults(service):
    before = datetime.now(timezone.utc)
    stored = await service.emit(
        EventType.CALL_STARTED, tenant_id=TENANT, payload={"to_number": "+1555"}
    )
    e = stored.event
    assert e.event_id  # auto uuid
    assert e.tenant_id == TENANT
    assert e.occurred_at >= before  # server-side timestamp
    assert stored.seq == 1
    assert e.payload["direction"] == "outbound"  # payload default applied


async def test_emit_requires_tenant(service):
    with pytest.raises(EventValidationError):
        await service.emit(EventType.CALL_STARTED, tenant_id="", payload={})


async def test_emit_rejects_bad_payload_before_persist(service):
    with pytest.raises(EventValidationError) as ei:
        await service.emit(EventType.GUARDRAIL_TRIPPED, tenant_id=TENANT, payload={})
    # nothing was persisted — the log is still empty
    assert service.query(EventQuery(tenant_id=TENANT)) == []
    assert "guardrail" in (ei.value.detail or "")


async def test_emit_persists_and_is_queryable(service):
    await service.emit(
        EventType.LEAD_OUTCOME, tenant_id=TENANT, campaign_id="c1",
        payload={"outcome": "qualified"},
    )
    rows = service.query(EventQuery(tenant_id=TENANT, campaign_id="c1"))
    assert len(rows) == 1
    assert rows[0].event.type is EventType.LEAD_OUTCOME


async def test_correlation_ids_are_stored(service):
    stored = await service.emit(
        EventType.CALL_STARTED, tenant_id=TENANT, campaign_id="c1",
        lead_id="l1", call_id="k1", agent_id="a1", payload={},
    )
    e = stored.event
    assert (e.campaign_id, e.lead_id, e.call_id, e.agent_id) == ("c1", "l1", "k1", "a1")


async def test_severity_passthrough(service):
    stored = await service.emit(
        EventType.GUARDRAIL_TRIPPED, tenant_id=TENANT, severity=Severity.CRITICAL,
        payload={"guardrail": "dnc"},
    )
    assert stored.event.severity is Severity.CRITICAL
