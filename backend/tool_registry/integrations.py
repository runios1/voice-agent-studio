"""Mock provider clients — the downstream calendar/email APIs, stubbed.

This workstream OWNS guardrailed execution, not the real Google integration. So the
outbound side is a pair of tiny fakes that model the shape of the real call
(authenticated, returns a provider id) without any network. The handler passes the
tenant's decrypted access token in, proving the execution path runs against the
tenant's OWN credential — the real Google client swaps in behind the same method
signatures (D9 posture), no handler change.

Approved email templates live here too, as a stand-in for the platform's template
store. A template is pre-authored copy plus any baked-in links — the model never
composes either; it only names a template id (see catalog + guardrails).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.tool_registry.errors import ProviderError


@dataclass
class BookedSlot:
    provider_event_id: str
    start_iso: str
    end_iso: str


class MockCalendarClient:
    """Stand-in for a Google Calendar client. Records what it 'booked' so tests and
    the audit trail can see it. Requires a non-empty access token — a missing token
    is a hard failure, mirroring a real 401."""

    def __init__(self) -> None:
        self.booked: list[BookedSlot] = []

    def book(
        self, access_token: str, start: datetime, length_minutes: int
    ) -> BookedSlot:
        if not access_token:
            raise ProviderError("Missing calendar credential.")
        end = start + timedelta(minutes=length_minutes)
        slot = BookedSlot(
            provider_event_id=f"evt-{len(self.booked) + 1}",
            start_iso=start.isoformat(),
            end_iso=end.isoformat(),
        )
        self.booked.append(slot)
        return slot


@dataclass
class EmailTemplate:
    template_id: str
    subject: str
    body: str
    links: list[str] = field(default_factory=list)  # baked-in URLs, allowlist-checked


@dataclass
class SentEmail:
    provider_message_id: str
    template_id: str


class MockEmailClient:
    """Stand-in for a Gmail send client. Holds the approved template store and
    records sends. Never accepts a free-composed body/link — only a template id."""

    def __init__(self, templates: list[EmailTemplate] | None = None) -> None:
        self.templates: dict[str, EmailTemplate] = {
            t.template_id: t for t in (templates or [])
        }
        self.sent: list[SentEmail] = []

    def get_template(self, template_id: str) -> EmailTemplate:
        tpl = self.templates.get(template_id)
        if tpl is None:
            raise ProviderError("No such email template.")
        return tpl

    def send(self, access_token: str, template: EmailTemplate) -> SentEmail:
        if not access_token:
            raise ProviderError("Missing email credential.")
        msg = SentEmail(
            provider_message_id=f"msg-{len(self.sent) + 1}",
            template_id=template.template_id,
        )
        self.sent.append(msg)
        return msg
