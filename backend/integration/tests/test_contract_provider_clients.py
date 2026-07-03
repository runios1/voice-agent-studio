"""The frozen `provider_clients` contract must match the shape the handlers actually use.
The in-repo mocks are the reference implementation, so they MUST satisfy it — if this breaks,
the contract drifted from the caller, and the real P3-1/P3-2 clients would too.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts.provider_clients.interface import (
    CalendarBooking,
    CalendarClient,
    EmailClient,
    EmailTemplate,
    SentEmailReceipt,
)
from backend.tool_registry.integrations import (
    EmailTemplate as MockTemplate,
    MockCalendarClient,
    MockEmailClient,
)


def test_mock_calendar_client_satisfies_contract():
    client = MockCalendarClient()
    assert isinstance(client, CalendarClient)
    slot = client.book("tok", datetime(2026, 7, 10, 10, tzinfo=timezone.utc), 30)
    assert isinstance(slot, CalendarBooking)
    assert slot.provider_event_id and slot.start_iso and slot.end_iso


def test_mock_email_client_satisfies_contract():
    tpl = MockTemplate(template_id="intro", subject="Hi", body="Hello", links=[])
    client = MockEmailClient([tpl])
    assert isinstance(client, EmailClient)
    got = client.get_template("intro")
    assert isinstance(got, EmailTemplate)
    receipt = client.send("tok", got)
    assert isinstance(receipt, SentEmailReceipt)
    assert receipt.provider_message_id and receipt.template_id == "intro"
