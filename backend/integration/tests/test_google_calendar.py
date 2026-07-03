"""GoogleCalendarClient — unit tests against a stubbed `httpx.post` (no network).

Live smoke (documented, not run in CI): set `GOOGLE_OAUTH_CLIENT_ID/SECRET`, connect a
real Google account through `/api/connections/google_calendar/authorize` +
`/api/oauth/callback`, then run a campaign with calendar enabled and confirm a real
event lands on the connected calendar (masked account in the event log).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.provider_clients.interface import CalendarBooking, CalendarClient
from backend.integration.google_calendar import GoogleCalendarClient
from backend.tool_registry.errors import ProviderError


class _Resp:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _patch_post(monkeypatch, fn):
    import httpx

    monkeypatch.setattr(httpx, "post", fn)


def test_satisfies_the_frozen_contract(monkeypatch):
    _patch_post(
        monkeypatch,
        lambda *a, **kw: _Resp(
            200, {"id": "evt_1", "start": {"dateTime": "x"}, "end": {"dateTime": "y"}}
        ),
    )
    client = GoogleCalendarClient()
    assert isinstance(client, CalendarClient)
    slot = client.book("tok", datetime(2026, 7, 10, 10, tzinfo=timezone.utc), 30)
    assert isinstance(slot, CalendarBooking)


def test_book_posts_start_end_and_returns_the_provider_event(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((url, json, headers, params))
        return _Resp(
            200,
            {
                "id": "evt_42",
                "start": {"dateTime": "2026-07-10T10:00:00+00:00"},
                "end": {"dateTime": "2026-07-10T10:30:00+00:00"},
            },
        )

    _patch_post(monkeypatch, fake_post)
    client = GoogleCalendarClient()
    start = datetime(2026, 7, 10, 10, tzinfo=timezone.utc)
    booking = client.book("tok-abc", start, 30)

    assert booking.provider_event_id == "evt_42"
    assert booking.start_iso == "2026-07-10T10:00:00+00:00"
    assert booking.end_iso == "2026-07-10T10:30:00+00:00"

    [(url, body, headers, params)] = calls
    assert url == "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    assert headers["Authorization"] == "Bearer tok-abc"
    assert body["start"]["dateTime"] == start.isoformat()
    assert "timeZone" not in body["start"]  # aware datetime — no zone override needed
    assert "attendees" not in body
    assert params == {}


def test_naive_start_gets_an_explicit_utc_timezone(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append(json)
        return _Resp(200, {"id": "evt_1", "start": {}, "end": {}})

    _patch_post(monkeypatch, fake_post)
    client = GoogleCalendarClient()
    client.book("tok", datetime(2026, 7, 10, 10, 0, 0), 30)

    [body] = calls
    assert body["start"]["timeZone"] == "UTC"
    assert body["end"]["timeZone"] == "UTC"


def test_attendee_email_adds_attendee_and_requests_send_updates(monkeypatch):
    calls = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((json, params))
        return _Resp(200, {"id": "evt_1", "start": {}, "end": {}})

    _patch_post(monkeypatch, fake_post)
    client = GoogleCalendarClient()
    client.book(
        "tok",
        datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
        30,
        attendee_email="lead@example.com",
    )

    [(body, params)] = calls
    assert body["attendees"] == [{"email": "lead@example.com"}]
    assert params == {"sendUpdates": "all"}  # a query param, not a body field


def test_busy_periods_parses_the_freebusy_response(monkeypatch):
    import httpx

    calls = []

    def fake_post(url, json, headers, timeout):
        calls.append((url, json))
        return _Resp(
            200,
            {
                "calendars": {
                    "primary": {
                        "busy": [
                            {
                                "start": "2026-07-10T10:00:00+00:00",
                                "end": "2026-07-10T10:30:00+00:00",
                            }
                        ]
                    }
                }
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = GoogleCalendarClient()
    start = datetime(2026, 7, 10, 8, tzinfo=timezone.utc)
    end = datetime(2026, 7, 10, 18, tzinfo=timezone.utc)
    busy = client.busy_periods("tok", start, end)

    assert busy == [
        (
            datetime(2026, 7, 10, 10, tzinfo=timezone.utc),
            datetime(2026, 7, 10, 10, 30, tzinfo=timezone.utc),
        )
    ]
    [(url, body)] = calls
    assert url == "https://www.googleapis.com/calendar/v3/freeBusy"
    assert body["items"] == [{"id": "primary"}]
    assert body["timeMin"] == start.isoformat()


def test_busy_periods_missing_access_token_is_a_provider_error():
    client = GoogleCalendarClient()
    with pytest.raises(ProviderError):
        client.busy_periods(
            "",
            datetime(2026, 7, 10, 8, tzinfo=timezone.utc),
            datetime(2026, 7, 10, 18, tzinfo=timezone.utc),
        )


def test_missing_access_token_is_a_provider_error(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **kw: _Resp(200, {"id": "x"}))
    client = GoogleCalendarClient()
    with pytest.raises(ProviderError):
        client.book("", datetime(2026, 7, 10, 10, tzinfo=timezone.utc), 30)


def test_non_2xx_response_is_mapped_to_provider_error_not_leaked(monkeypatch):
    _patch_post(
        monkeypatch,
        lambda *a, **kw: _Resp(401, {"error": {"message": "invalid_grant: token expired"}}),
    )
    client = GoogleCalendarClient()
    with pytest.raises(ProviderError) as exc:
        client.book("tok", datetime(2026, 7, 10, 10, tzinfo=timezone.utc), 30)
    assert "invalid_grant" not in str(exc.value)  # generic, client-safe (least context)


def test_transport_failure_is_mapped_to_provider_error(monkeypatch):
    import httpx

    def boom(*a, **kw):
        raise httpx.ConnectError("boom")

    _patch_post(monkeypatch, boom)
    client = GoogleCalendarClient()
    with pytest.raises(ProviderError):
        client.book("tok", datetime(2026, 7, 10, 10, tzinfo=timezone.utc), 30)


def test_missing_event_id_is_a_provider_error(monkeypatch):
    _patch_post(monkeypatch, lambda *a, **kw: _Resp(200, {"start": {}, "end": {}}))
    client = GoogleCalendarClient()
    with pytest.raises(ProviderError):
        client.book("tok", datetime(2026, 7, 10, 10, tzinfo=timezone.utc), 30)
