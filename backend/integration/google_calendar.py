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
import logging
from typing import Optional, Sequence

from backend.tool_registry.errors import ProviderError

log = logging.getLogger("voice_agent_studio.google_calendar")

_EVENTS_URL_TMPL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"


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
        """Busy intervals in [start, end), read via `events.list`.

        Deliberately NOT `freeBusy.query`: freeBusy needs a broader Calendar scope
        (`calendar`/`calendar.readonly`) than the least-privilege `calendar.events`
        scope this integration requests and that booking (`events.insert`) already
        uses — so freeBusy returns 403 on a connection scoped only for booking. Listing
        events on the primary calendar gives the same busy intervals within the scope
        we already hold, so availability and booking work off one consent.
        """
        if not access_token:
            raise ProviderError("Missing calendar credential.")

        import httpx  # lazy: no network/SDK cost at import time (D8)

        url = _EVENTS_URL_TMPL.format(calendar_id=self._calendar_id)
        params = {
            "timeMin": _rfc3339(start),
            "timeMax": _rfc3339(end),
            "singleEvents": "true",   # expand recurring events into instances
            "orderBy": "startTime",
            "maxResults": "250",
        }
        try:
            resp = httpx.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            log.warning("calendar events.list transport error: %s", exc)
            raise ProviderError("Calendar provider request failed.")

        if resp.status_code >= 400:
            # Log the status server-side (never the body — may carry account detail) so
            # a real failure is diagnosable; the caller still gets a generic error.
            log.warning("calendar events.list rejected: status=%s", resp.status_code)
            raise ProviderError(
                f"Calendar provider rejected the availability lookup (status {resp.status_code})."
            )

        data = resp.json()
        busy: list[tuple[datetime, datetime]] = []
        for item in data.get("items", []):
            if item.get("status") == "cancelled":
                continue
            if item.get("transparency") == "transparent":
                continue  # the event owner marked this time as "free" / non-blocking
            b_start = (item.get("start") or {}).get("dateTime")
            b_end = (item.get("end") or {}).get("dateTime")
            if not b_start or not b_end:
                continue  # all-day (date-only) or malformed — not a timed conflict
            try:
                busy.append((datetime.fromisoformat(b_start), datetime.fromisoformat(b_end)))
            except ValueError:
                continue
        return busy
