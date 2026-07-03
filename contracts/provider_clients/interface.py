"""FROZEN CONTRACT — the provider-client swap boundary (Phase 3).

The tool handlers (`backend/tool_registry/handlers.py`) call a calendar/email client behind
a fixed, minimal method surface (D9: "the real Google client swaps in behind the same
method signatures, no handler change"). Phase 3 replaces the in-repo MOCK clients with real
Google Calendar / Resend clients. This module freezes the EXACT surface both sides agree on,
so P3-1 (calendar) and P3-2 (email) can be built in parallel and drop straight in.

These are structural `Protocol`s: the existing mock dataclasses already satisfy them, and a
real client satisfies them by exposing the same attributes/methods — no inheritance, no
import from the mocks. Do NOT widen these without a contract-change-request: the handler is
the only caller and it relies on exactly these fields.

Security invariants the handler guarantees (a client MUST rely on them, not re-check):
  * `access_token` is the calling TENANT'S OWN decrypted token, resolved by the credential
    store in code. A client never selects a tenant or reads a token store itself.
  * The handler enforces guardrails (calling hours, booking window, template allow-list,
    link allow-list) BEFORE calling the client. A client performs the action; it is not the
    guardrail. It MUST raise `ProviderError` (from backend.tool_registry.errors) — never a
    raw SDK exception — on a provider failure (a real 401/5xx), so the handler surfaces a
    clean, model-recoverable error and the SDK never leaks past the adapter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class CalendarBooking(Protocol):
    """What `CalendarClient.book` returns. ISO-8601 strings so the event payload is
    JSON-serializable straight onto the audit log."""

    provider_event_id: str
    start_iso: str
    end_iso: str


@runtime_checkable
class CalendarClient(Protocol):
    """Holds a meeting slot on the tenant's connected calendar."""

    def book(
        self, access_token: str, start: datetime, length_minutes: int
    ) -> CalendarBooking:
        """Book `length_minutes` from `start` on the tenant's primary calendar and return
        the created event. Raise `ProviderError` on any provider failure (incl. a missing/
        rejected token). `start` may be tz-aware or naive; a real client should treat naive
        as the tenant's calendar-default zone."""
        ...


@runtime_checkable
class EmailTemplate(Protocol):
    """A pre-authored, approved template. The MODEL never composes body or links — it only
    names a `template_id`; the body and every baked-in link are fixed here. The handler
    re-screens `links` against the locked allow-list at send time."""

    template_id: str
    subject: str
    body: str
    links: Sequence[str]


@runtime_checkable
class SentEmailReceipt(Protocol):
    """What `EmailClient.send` returns."""

    provider_message_id: str
    template_id: str


@runtime_checkable
class EmailClient(Protocol):
    """Sends one APPROVED template (never a free-composed message) as the tenant."""

    def get_template(self, template_id: str) -> EmailTemplate:
        """Return the approved template for `template_id`. Raise `ProviderError` if there is
        no such template (the id space is the agent's approved set — an unknown id is a bug
        upstream, never a place to compose new copy)."""
        ...

    def send(self, access_token: str, template: EmailTemplate) -> SentEmailReceipt:
        """Send `template` to the lead as the tenant and return the provider receipt. Raise
        `ProviderError` on any provider failure. MUST NOT alter subject/body/links."""
        ...
