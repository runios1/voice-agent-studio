"""Real Google Calendar client — P3-1's `CalendarClient` (`contracts/provider_clients`).

Talks to the Calendar v3 REST API directly over `httpx` (no Google SDK dependency;
the surface we need is one `events.insert` call). `httpx` is imported lazily inside
`book()` so importing this module carries no network/SDK cost — the real client only
touches the wire when a booking actually runs (D8: provider SDKs lazily imported
inside their adapter).

`book` is intentionally SYNCHRONOUS: it satisfies `contracts.provider_clients.
CalendarClient.book`, whose signature is sync (matching `MockCalendarClient` and the
handler's call site in `backend/tool_registry/handlers.py`, which calls it without
`await`). A blocking `httpx.post` is acceptable here — one short REST call per booking,
same posture as the mock it replaces.

Per the contract's note on naive datetimes: a naive `start` is treated as the tenant's
calendar-default zone by omitting a UTC offset and passing an explicit `timeZone` so
Google resolves it against the calendar's own zone rather than guessing.

Known gap (acceptable for v1): `access_token` is used as handed to us; there is no
in-adapter refresh-on-401 retry. Google access tokens are short-lived (~1h) but the
credential store already retains the refresh token — wiring a refresh path is a
follow-up (would touch `EncryptedCredentialStore`'s read path), not required for this
workstream's DONE criteria.

`busy_periods` (live-preview scheduling feature) hits `freeBusy.query` — a read, no
event created — so the agent can compute real open slots before proposing one.
`book`'s optional `attendee_email` adds the lead as an event attendee with
`sendUpdates=all`: this is the platform's actual "send a meeting invite" mechanism —
Google emails the invite itself, there is no separate invite-send call to make.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from backend.tool_registry.errors import ProviderError

_EVENTS_URL_TMPL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
_FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"


@dataclass
class CalendarBooking:
    """Satisfies `contracts.provider_clients.CalendarBooking`."""

    provider_event_id: str
    start_iso: str
    end_iso: str


def _event_time(dt: datetime) -> dict:
    """Google's `EventDateTime` shape. Naive `dt` gets an explicit `timeZone` instead
    of a guessed UTC offset, so it resolves against the tenant's own calendar zone."""
    if dt.tzinfo is None:
        return {"dateTime": dt.isoformat(), "timeZone": "UTC"}
    return {"dateTime": dt.isoformat()}


def _rfc3339(dt: datetime) -> str:
    """`freeBusy.query`'s `timeMin`/`timeMax` are plain RFC3339 strings — unlike
    `events.insert` there is no sibling `timeZone` field to pair with a naive
    timestamp, so a naive `dt` is stamped UTC directly (matches `_event_time`'s
    naive-as-UTC convention elsewhere in this client)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class GoogleCalendarClient:
    """Real `CalendarClient`: books on the tenant's primary Google Calendar."""

    def __init__(self, *, calendar_id: str = "primary", timeout: float = 10.0):
        self._calendar_id = calendar_id
        self._timeout = timeout

    def book(
        self,
        access_token: str,
        start: datetime,
        length_minutes: int,
        attendee_email: Optional[str] = None,
    ) -> CalendarBooking:
        if not access_token:
            raise ProviderError("Missing calendar credential.")

        import httpx  # lazy: no network/SDK cost at import time (D8)

        end = start + timedelta(minutes=length_minutes)
        body = {"start": _event_time(start), "end": _event_time(end)}
        url = _EVENTS_URL_TMPL.format(calendar_id=self._calendar_id)
        params = {}
        if attendee_email:
            body["attendees"] = [{"email": attendee_email}]
            # Query param, not a body field — this is what makes Google actually email
            # the invite to the attendee instead of silently adding them.
            params["sendUpdates"] = "all"

        try:
            resp = httpx.post(
                url,
                json=body,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            raise ProviderError("Calendar provider request failed.")

        if resp.status_code >= 400:
            # Never leak the provider's raw body (may carry account/billing detail).
            raise ProviderError(
                f"Calendar provider rejected the booking (status {resp.status_code})."
            )

        data = resp.json()
        event_id = data.get("id")
        if not event_id:
            raise ProviderError("Calendar provider did not return an event id.")
        start_iso = (data.get("start") or {}).get("dateTime") or start.isoformat()
        end_iso = (data.get("end") or {}).get("dateTime") or end.isoformat()
        return CalendarBooking(
            provider_event_id=event_id, start_iso=start_iso, end_iso=end_iso
        )

    def busy_periods(
        self, access_token: str, start: datetime, end: datetime
    ) -> Sequence[tuple[datetime, datetime]]:
        if not access_token:
            raise ProviderError("Missing calendar credential.")

        import httpx  # lazy: no network/SDK cost at import time (D8)

        body = {
            "timeMin": _rfc3339(start),
            "timeMax": _rfc3339(end),
            "items": [{"id": self._calendar_id}],
        }
        try:
            resp = httpx.post(
                _FREEBUSY_URL,
                json=body,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            raise ProviderError("Calendar provider request failed.")

        if resp.status_code >= 400:
            raise ProviderError(
                f"Calendar provider rejected the freebusy query (status {resp.status_code})."
            )

        data = resp.json()
        cal = (data.get("calendars") or {}).get(self._calendar_id) or {}
        busy = []
        for period in cal.get("busy", []):
            b_start = period.get("start")
            b_end = period.get("end")
            if not b_start or not b_end:
                continue
            busy.append((datetime.fromisoformat(b_start), datetime.fromisoformat(b_end)))
        return busy
