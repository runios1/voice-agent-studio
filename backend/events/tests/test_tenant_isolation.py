"""Tenant isolation (D-security) — no read/subscribe ever crosses tenants."""

from __future__ import annotations

from contracts.events.schema import EventType
from backend.events.store import EventQuery
from .conftest import TENANT, OTHER


async def test_query_never_returns_other_tenant(service):
    await service.emit(EventType.CALL_STARTED, tenant_id=TENANT, payload={})
    await service.emit(EventType.CALL_STARTED, tenant_id=OTHER, payload={})
    mine = service.query(EventQuery(tenant_id=TENANT))
    assert len(mine) == 1
    assert all(s.event.tenant_id == TENANT for s in mine)


async def test_get_is_tenant_scoped(service):
    stored = await service.emit(EventType.CALL_STARTED, tenant_id=TENANT, payload={})
    assert service.get(TENANT, stored.event.event_id) is not None
    # another tenant asking for the same id gets nothing (existence not leaked)
    assert service.get(OTHER, stored.event.event_id) is None


async def test_subscribe_only_sees_own_tenant(service):
    sub = service.subscribe(EventQuery(tenant_id=TENANT))
    await service.emit(EventType.CALL_STARTED, tenant_id=OTHER, payload={})
    await service.emit(EventType.CALL_STARTED, tenant_id=TENANT, payload={})
    got = []
    async for s in sub:
        got.append(s)
        if len(got) == 1:
            sub.close()
    assert len(got) == 1
    assert got[0].event.tenant_id == TENANT
