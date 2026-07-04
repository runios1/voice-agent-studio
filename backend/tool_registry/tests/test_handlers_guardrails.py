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


async def test_attendee_email_is_validated_and_passed_to_the_client(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    result = await reg.execute(
        "calendar",
        {"start_iso": _at(1, 15), "attendee_email": "lead@acme.co"},
        TENANT,
    )
    assert result["attendee_email"] == "lead@acme.co"
    assert calendar_client.booked[0].attendee_email == "lead@acme.co"


async def test_naive_booking_time_is_interpreted_as_platform_local(
    connections, credentials, sink, calendar_client, manager
):
    # A time with no offset must book at the platform-local wall-clock, not UTC — the
    # bug where an Israel (UTC+3) booking landed 3 hours ahead.
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from backend.tool_registry.guardrails import platform_tz

    config = make_config(email_enabled=False, calling_hours=(0, 23))
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    naive = (_dt.now(_tz.utc) + _td(days=1)).replace(
        hour=15, minute=0, second=0, microsecond=0, tzinfo=None
    ).isoformat()

    result = await reg.execute("calendar", {"start_iso": naive}, TENANT)

    booked = _dt.fromisoformat(result["start_iso"])
    assert booked.tzinfo is not None  # localized, not left naive
    # the local wall-clock hour is preserved as 15:00 local (not shifted into UTC)
    assert booked.astimezone(platform_tz()).hour == 15


async def test_malformed_attendee_email_is_rejected_and_trips(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    with pytest.raises(GuardrailViolation) as ex:
        await reg.execute(
            "calendar", {"start_iso": _at(1, 15), "attendee_email": "not-an-email"}, TENANT
        )
    assert ex.value.param == "attendee_email"
    assert calendar_client.booked == []


async def test_placeholder_example_attendee_email_is_rejected(
    connections, credentials, sink, calendar_client, manager
):
    # A voice model routinely substitutes a heard address with example.com; sending a
    # real lead's confirmation there is a privacy bug, so a reserved/placeholder domain
    # is refused (the booking trips rather than silently mailing a fake address).
    config = make_config(email_enabled=False)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    for bad in ("lead@example.com", "lead@example.org", "someone@foo.test", "x@internal.localhost"):
        with pytest.raises(GuardrailViolation) as ex:
            await reg.execute(
                "calendar", {"start_iso": _at(1, 15), "attendee_email": bad}, TENANT
            )
        assert ex.value.param == "attendee_email"
    assert calendar_client.booked == []


# --------------------------- check_availability ---------------------------
def _tomorrow_date_iso() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()


async def test_availability_returns_open_slots_within_calling_hours(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False, calling_hours=(9, 17))
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    result = await reg.execute(
        "check_availability", {"date_iso": _tomorrow_date_iso()}, TENANT
    )
    assert result["available"] is True
    assert result["slots"]
    for iso in result["slots"]:
        hour = datetime.fromisoformat(iso).hour
        assert 9 <= hour < 17


async def test_availability_excludes_busy_periods(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False, calling_hours=(9, 17))
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    # Block the whole calling-hours window, defined in the platform-local tz (calling
    # hours are local now, not UTC).
    from backend.tool_registry.guardrails import platform_tz

    tz = platform_tz()
    d = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    calendar_client.busy = [
        (datetime(d.year, d.month, d.day, 9, tzinfo=tz), datetime(d.year, d.month, d.day, 17, tzinfo=tz))
    ]

    result = await reg.execute(
        "check_availability", {"date_iso": _tomorrow_date_iso()}, TENANT
    )
    assert result == {"available": False, "slots": []}


async def test_availability_invalid_date_is_rejected(
    connections, credentials, sink, calendar_client, manager
):
    config = make_config(email_enabled=False)
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    with pytest.raises(GuardrailViolation) as ex:
        await reg.execute("check_availability", {"date_iso": "not-a-date"}, TENANT)
    assert ex.value.param == "date_iso"


async def test_availability_slots_for_today_are_never_immediately_stale(
    connections, credentials, sink, calendar_client, manager
):
    # Regression: an earlier version returned a slot starting at exactly `now`, which
    # had already fallen into the past by the time a real conversation got around to
    # booking it moments later — check_within_booking_window then rejected it even
    # though check_availability had just offered it. Every returned slot must still
    # book cleanly.
    config = make_config(email_enabled=False, calling_hours=(0, 23))
    reg = await _calendar_registry(config, connections, credentials, sink, calendar_client, manager)
    today = datetime.now(timezone.utc).date().isoformat()

    result = await reg.execute("check_availability", {"date_iso": today}, TENANT)
    assert result["slots"]
    for slot in result["slots"]:
        assert datetime.fromisoformat(slot) > datetime.now(timezone.utc)

    booked = await reg.execute("calendar", {"start_iso": result["slots"][0]}, TENANT)
    assert booked["booked"] is True


# --------------------------- email ---------------------------
async def _email_registry(config, connections, credentials, sink, email_client, manager):
    await _connect(manager, EMAIL_PROVIDER)
    return build_registry(
        config, connections, credentials, sink=sink, email_client=email_client
    )


async def _execute_email(reg, args, tenant, *, lead_email="lead@example.com"):
    """`ToolContext.lead_email` is attached by trusted caller code (see
    `backend/live_agent/session.py`'s post-call email step) — never a tool arg — so
    tests build it the same way instead of going through `reg.execute`, which has no
    lead_email parameter by design (a single deliberate caller, not a generic path)."""
    ctx = reg.resolve_context("email", tenant)
    ctx = ctx.model_copy(update={"lead_email": lead_email})
    return await reg.handler_for("email").execute(args, ctx)


async def test_approved_allowlisted_template_sends(
    connections, credentials, sink, email_client, manager
):
    config = make_config(
        calendar_enabled=False,
        template_ids=["confirm"],
        allowed_link_domains=["acme.com"],
    )
    reg = await _email_registry(config, connections, credentials, sink, email_client, manager)
    result = await _execute_email(reg, {"template_id": "confirm"}, TENANT)
    assert result["sent"] is True
    assert len(email_client.sent) == 1
    assert email_client.sent[0].to_address == "lead@example.com"
    assert sink.of_type(EventType.TOOL_INVOKED)


async def test_missing_lead_email_is_rejected(
    connections, credentials, sink, email_client, manager
):
    config = make_config(calendar_enabled=False, template_ids=["confirm"])
    reg = await _email_registry(config, connections, credentials, sink, email_client, manager)
    with pytest.raises(GuardrailViolation) as ex:
        await _execute_email(reg, {"template_id": "confirm"}, TENANT, lead_email=None)
    assert ex.value.param == "lead_email"
    assert email_client.sent == []


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
        await _execute_email(reg, {"template_id": "bad-link"}, TENANT)
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
    result = await _execute_email(reg, {"template_id": "sub"}, TENANT)
    assert result["sent"] is True
