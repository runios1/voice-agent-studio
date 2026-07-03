"""build_registry wiring + the cross-tenant denial end-to-end."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from contracts.tool_registry.interface import Connection, Timing, ToolContext
from backend.tool_registry.errors import NotConnected, TenantAccessDenied, UnknownTool
from backend.tool_registry.registry import build_registry

from .conftest import CALENDAR_PROVIDER, OTHER, REDIRECT, TENANT, make_config


async def _connect(manager, tenant, provider):
    url = manager.begin_connect(tenant, provider, ["s"], REDIRECT)
    state = parse_qs(urlparse(url).query)["state"][0]
    return await manager.complete_connect(state, code="c")


def _future_slot(hour=15, days=1):
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def test_disabled_automation_yields_no_tool(connections, credentials):
    # Structural denial: a disabled block produces no tool to call at all (Phase-1 rule).
    config = make_config(calendar_enabled=False, email_enabled=True, template_ids=["t"])
    reg = build_registry(config, connections, credentials)
    assert reg.get("calendar") is None
    assert reg.get("email") is not None
    with pytest.raises(UnknownTool):
        reg.handler_for("calendar")


def test_both_enabled_exposes_both(connections, credentials):
    config = make_config(template_ids=["t"])
    reg = build_registry(config, connections, credentials)
    assert {t.name for t in reg.list_tools()} == {"calendar", "check_availability", "email"}


def test_list_tools_filters_by_timing(connections, credentials):
    config = make_config(template_ids=["t"])
    reg = build_registry(config, connections, credentials)
    assert set(t.name for t in reg.list_tools(Timing.IN_CALL)) == {
        "calendar",
        "check_availability",
    }
    assert [t.name for t in reg.list_tools(Timing.POST_CALL)] == ["email"]


def test_check_availability_rides_the_calendar_gate(connections, credentials):
    # No automation block of its own — disabled/enabled follows calendar exactly.
    disabled = make_config(calendar_enabled=False, email_enabled=True, template_ids=["t"])
    reg = build_registry(disabled, connections, credentials)
    assert reg.get("check_availability") is None
    with pytest.raises(UnknownTool):
        reg.handler_for("check_availability")

    enabled = make_config(template_ids=["t"])
    reg2 = build_registry(enabled, connections, credentials)
    assert reg2.get("check_availability") is not None


def test_email_param_enum_is_narrowed_to_approved_ids(connections, credentials):
    config = make_config(calendar_enabled=False, template_ids=["confirm", "welcome"])
    reg = build_registry(config, connections, credentials)
    enum = reg.get("email").params["properties"]["template_id"]["enum"]
    assert enum == ["confirm", "welcome"]


def test_empty_allowlist_makes_email_uncallable_structurally(connections, credentials):
    # No approved templates -> enum [] -> the model has no valid call to make.
    config = make_config(calendar_enabled=False, template_ids=[])
    reg = build_registry(config, connections, credentials)
    assert reg.get("email").params["properties"]["template_id"]["enum"] == []


async def test_resolve_context_attaches_the_tenants_own_connection(
    connections, credentials, manager
):
    await _connect(manager, TENANT, CALENDAR_PROVIDER)
    config = make_config(email_enabled=False)
    reg = build_registry(config, connections, credentials)
    ctx = reg.resolve_context("calendar", TENANT)
    assert ctx.connection is not None
    assert ctx.connection.tenant_id == TENANT


async def test_other_tenant_has_no_connection_so_execution_is_blocked(
    connections, credentials, calendar_client, manager
):
    # Alice connects; Bob (no connection) tries to run the tool -> nothing to act on.
    await _connect(manager, TENANT, CALENDAR_PROVIDER)
    config = make_config(email_enabled=False)
    reg = build_registry(config, connections, credentials, calendar_client=calendar_client)
    with pytest.raises(NotConnected):
        await reg.execute("calendar", {"start_iso": _future_slot()}, OTHER)
    assert calendar_client.booked == []


async def test_forged_context_with_another_tenants_ref_is_denied(
    connections, credentials, calendar_client, manager
):
    # The hard case: a forged ToolContext claiming Bob's tenant but carrying Alice's
    # connection_ref. The credential store re-checks ownership -> denied. Belt+braces
    # on top of the store-level tenant filter.
    conn = await _connect(manager, TENANT, CALENDAR_PROVIDER)
    config = make_config(email_enabled=False)
    reg = build_registry(config, connections, credentials, calendar_client=calendar_client)
    handler = reg.handler_for("calendar")
    forged = ToolContext(
        tenant_id=OTHER,
        connection=Connection(
            tenant_id=OTHER,  # lies about ownership...
            provider=CALENDAR_PROVIDER,
            connection_ref=conn.connection_ref,  # ...but points at Alice's ref
        ),
    )
    with pytest.raises(TenantAccessDenied):
        await handler.execute({"start_iso": _future_slot()}, forged)
    assert calendar_client.booked == []
