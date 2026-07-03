"""Handlers are the enforcement point — guardrails bite here, in code (D6)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from contracts.events.schema import EventType, Severity
from backend.tool_registry.errors import GuardrailViolation
from backend.tool_registry.registry import build_registry

from .conftest import (
    CALENDAR_PROVIDER,
    EMAIL_PROVIDER,
    REDIRECT,
    TENANT,
    make_config,
)


def _at(days_from_now: float, hour: int) -> str:
    base = datetime.now(timezone.utc) + timedelta(days=days_from_now)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


async def _connect(manager, provider):
    url = manager.begin_connect(TENANT, provider, ["s"], REDIRECT)
    from urllib.parse import parse_qs, urlparse

    state = parse_qs(urlparse(url).query)["state"][0]
    return await manager.complete_connect(state, code="c")


# --------------------------- calendar ---------------------------
async def _calendar_registry(config, connections, credentials, sink, calendar_client, manager):
    await _connect(manager, CALENDAR_PROVIDER)
    return build_registry(
        config, connections, credentials, sink=sink, calendar_client=calendar_client
    )


async def test_valid_slot_books_and_emits(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)

    result = await reg.execute("calendar", {"start_iso": _at(1, 15)}, TENANT)
    assert result["booked"] is True
    assert len(calendar_client.booked) == 1
    # Emits TOOL_INVOKED + SLOT_BOOKED, none of them a guardrail trip.
    types = [e.type for e in sink.events]
    assert EventType.TOOL_INVOKED in types
    assert EventType.SLOT_BOOKED in types
    assert EventType.GUARDRAIL_TRIPPED not in types


async def test_handler_event_payloads_match_the_events_contract(
    connections, credentials, sink, calendar_client, manager
):
    """The handler's emitted payloads must satisfy backend.events.payloads or the live
    EventService rejects them. Regression guard: the InMemoryEventSink here does not
    validate, which once let TOOL_INVOKED/SLOT_BOOKED/GUARDRAIL_TRIPPED ship with the
    wrong field names."""
    from backend.events.payloads import validate_payload

    config = make_config(email_enabled=False)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    await reg.execute("calendar", {"start_iso": _at(1, 15)}, TENANT)  # TOOL_INVOKED + SLOT_BOOKED
    with pytest.raises(GuardrailViolation):
        await reg.execute("calendar", {"start_iso": _at(1, 22)}, TENANT)  # GUARDRAIL_TRIPPED

    assert sink.events
    for e in sink.events:
        validate_payload(e.type, e.payload)  # raises if any payload is contract-wrong


async def test_out_of_hours_slot_is_rejected_and_trips(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False, calling_hours=(8, 20))
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)

    with pytest.raises(GuardrailViolation) as ex:
        await reg.execute("calendar", {"start_iso": _at(1, 22)}, TENANT)  # 22:00 local
    assert ex.value.param == "start_iso"
    assert calendar_client.booked == []  # no side effect
    trips = sink.of_type(EventType.GUARDRAIL_TRIPPED)
    assert len(trips) == 1 and trips[0].severity == Severity.WARNING


async def test_slot_beyond_booking_window_is_rejected(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False, booking_window_days=14)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    with pytest.raises(GuardrailViolation):
        await reg.execute("calendar", {"start_iso": _at(30, 15)}, TENANT)
    assert calendar_client.booked == []


async def test_slot_in_the_past_is_rejected(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    with pytest.raises(GuardrailViolation):
        await reg.execute("calendar", {"start_iso": _at(-1, 15)}, TENANT)


# --------------------------- email ---------------------------
async def _email_registry(config, connections, credentials, sink, email_client, manager):
    await _connect(manager, EMAIL_PROVIDER)
    return build_registry(
        config, connections, credentials, sink=sink, email_client=email_client
    )


async def test_approved_allowlisted_template_sends(
    connections, credentials, sink, email_client, manager
):
    config = make_config(
        calendar_enabled=False,
        template_ids=["confirm"],
        allowed_link_domains=["acme.com"],
    )
    reg = await _email_registry(config, connections, credentials, sink, email_client, manager)
    result = await reg.execute("email", {"template_id": "confirm"}, TENANT)
    assert result["sent"] is True
    assert len(email_client.sent) == 1
    assert sink.of_type(EventType.TOOL_INVOKED)


async def test_unapproved_template_is_rejected(
    connections, credentials, sink, email_client, manager
):
    config = make_config(calendar_enabled=False, template_ids=["confirm"], allowed_link_domains=["acme.com"])
    reg = await _email_registry(config, connections, credentials, sink, email_client, manager)
    # "plain" exists in the client but is NOT in this agent's approved list.
    with pytest.raises(GuardrailViolation) as ex:
        await reg.execute("email", {"template_id": "plain"}, TENANT)
    assert ex.value.param == "template_id"
    assert email_client.sent == []
    assert sink.of_type(EventType.GUARDRAIL_TRIPPED)


async def test_template_with_non_allowlisted_link_is_rejected(
    connections, credentials, sink, email_client, manager
):
    # Template is approved, but a baked-in link is off the platform allowlist.
    config = make_config(
        calendar_enabled=False,
        template_ids=["bad-link"],
        allowed_link_domains=["acme.com"],
    )
    reg = await _email_registry(config, connections, credentials, sink, email_client, manager)
    with pytest.raises(GuardrailViolation) as ex:
        await reg.execute("email", {"template_id": "bad-link"}, TENANT)
    assert ex.value.param == "link"
    assert email_client.sent == []


async def test_subdomain_of_allowlisted_domain_is_allowed(
    connections, credentials, sink, manager
):
    from backend.tool_registry.integrations import EmailTemplate, MockEmailClient

    client = MockEmailClient(
        templates=[EmailTemplate("sub", "s", "b", links=["https://mail.acme.com/x"])]
    )
    config = make_config(calendar_enabled=False, template_ids=["sub"], allowed_link_domains=["acme.com"])
    reg = await _email_registry(config, connections, credentials, sink, client, manager)
    result = await reg.execute("email", {"template_id": "sub"}, TENANT)
    assert result["sent"] is True
