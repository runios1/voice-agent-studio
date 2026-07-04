"""ResendEmailClient — the real email provider client (Phase 3, P3-2).

Implements `contracts.provider_clients.interface.EmailClient` (structural — no
inheritance, no import from the mocks) against Resend's HTTP send API
(https://api.resend.com/emails). Selected by
`backend/integration/providers.py::build_email_client()` when `RESEND_API_KEY` is
set; the mock (`backend.tool_registry.integrations.MockEmailClient`) runs otherwise.
Drops in behind the SAME method signatures the handler already calls (D9) — no
handler change.

Auth model: unlike Google Calendar (per-tenant OAuth), Resend is a single
platform-level sending account — one verified domain, one platform `RESEND_API_KEY`,
never a per-tenant token. `access_token` in `send()` is still the tenant's resolved
connection token (the frozen contract's shared shape, and its presence already proves
`_BaseHandler._access_token` found a live connection before calling us) but this
client does not use it to authenticate to Resend; it only asserts it is non-empty,
mirroring the mock's 401-shape check. Real auth is the injected/`env` `RESEND_API_KEY`.

Recipient (see `docs/contract-change-requests/p3-2-email-recipient-address.md`, now
partially applied for the live-preview path): `EmailClient.send` takes an explicit
`to_address`, resolved by `EmailHandler` from `ToolContext.lead_email`. The platform
stand-in address (`RESEND_DEV_RECIPIENT`) is now only a last-resort fallback if
`to_address` is somehow empty — it should not be hit on the normal path.

Approved templates: the model never composes a body or a link (D-security) — it only
names a `template_id`. Real template *content* is not yet a platform CMS;
`_DEFAULT_TEMPLATES` is a small static in-file catalog (same pattern as
`tool_registry/catalog.py`'s tool catalog), overridable via the `templates=`
constructor arg so a real store can drop in later with no client change.

No Resend SDK dependency (D8 lazy-import posture, kept dependency-light): this talks
to the plain REST endpoint over `httpx`, with the HTTP call itself swappable via
`poster=` so tests run with no network (mirrors P3-1's injected-poster pattern for
OAuth token exchange). Any transport failure or non-2xx response raises
`ProviderError` — the raw Resend error body never reaches the handler/model (least
context, D-security).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from backend.tool_registry.errors import ProviderError

log = logging.getLogger("voice_agent_studio.resend_email")

RESEND_API_URL = "https://api.resend.com/emails"


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
    to_address: Optional[str] = None


# Stand-in platform template store (see module docstring) — real copy only, the model
# never writes to these.
_DEFAULT_TEMPLATES: dict[str, EmailTemplate] = {
    # The default a booked meeting auto-confirms with — no links, so it clears the
    # allowlist screen with no per-agent domain config (this is what `capability_sync`
    # seeds into automation.email.template_ids when a tenant enables email).
    "booking_confirmation": EmailTemplate(
        template_id="booking_confirmation",
        subject="Your meeting is confirmed",
        body=(
            "Hi,\n\nThanks for your time today — this confirms the meeting we just "
            "scheduled. You'll also receive a calendar invite separately.\n\nLooking "
            "forward to it,\nThe team"
        ),
        links=[],
    ),
    "intro": EmailTemplate(
        template_id="intro",
        subject="Great speaking with you",
        body=(
            "Hi,\n\nThanks for the time today — here's a link to grab a slot that "
            "works for you.\n\nBest,\nThe team"
        ),
        links=["https://cal.example.com/book"],
    ),
    "follow_up": EmailTemplate(
        template_id="follow_up",
        subject="Following up",
        body="Hi,\n\nJust checking back in — happy to answer any questions.\n\nBest,\nThe team",
        links=[],
    ),
}

# A raw HTTP POST: (url, json_body, headers) -> object with `.status_code` / `.json()`.
# The default poster satisfies this with `httpx`; tests inject a stub with no network.
Poster = Callable[[str, dict, dict], object]


class ResendEmailClient:
    """Satisfies `contracts.provider_clients.interface.EmailClient`."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        from_address: Optional[str] = None,
        dev_recipient: Optional[str] = None,
        templates: Optional[dict[str, EmailTemplate]] = None,
        poster: Optional[Poster] = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_key = api_key or os.getenv("RESEND_API_KEY")
        if not self._api_key:
            raise ProviderError("Resend is not configured (RESEND_API_KEY missing).")
        self._from = from_address or os.getenv("RESEND_FROM_EMAIL")
        if not self._from:
            raise ProviderError("Resend is not configured (RESEND_FROM_EMAIL missing).")
        self._dev_recipient = dev_recipient or os.getenv("RESEND_DEV_RECIPIENT") or self._from
        self._templates: dict[str, EmailTemplate] = dict(
            templates if templates is not None else _DEFAULT_TEMPLATES
        )
        self._poster = poster or self._http_poster
        self._timeout = timeout_seconds

    # -- EmailClient ------------------------------------------------------- #

    def get_template(self, template_id: str) -> EmailTemplate:
        tpl = self._templates.get(template_id)
        if tpl is None:
            raise ProviderError("No such email template.")
        return tpl

    def send(self, access_token: str, to_address: str, template: EmailTemplate) -> SentEmail:
        if not access_token:
            raise ProviderError("Missing email connection.")

        to_address = to_address or self._recipient()
        payload = {
            "from": self._from,
            "to": [to_address],
            "subject": template.subject,
            "text": template.body,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = self._poster(RESEND_API_URL, payload, headers)
        except Exception as exc:  # transport-layer failure (timeout, DNS, ...)
            raise ProviderError("Email provider request failed.") from exc

        status = getattr(resp, "status_code", None)
        if status is None or status >= 400:
            raise ProviderError(
                f"Email provider rejected the send (status {status})."
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderError("Email provider returned an unreadable response.") from exc

        message_id = data.get("id") if isinstance(data, dict) else None
        if not message_id:
            raise ProviderError("Email provider response was missing a message id.")

        return SentEmail(
            provider_message_id=message_id,
            template_id=template.template_id,
            to_address=to_address,
        )

    # -- internals ----------------------------------------------------------- #

    def _recipient(self) -> str:
        # See the recipient-gap note in the module docstring / the filed CCR: the
        # frozen `EmailClient.send` signature carries no lead address yet.
        log.warning(
            "ResendEmailClient sending to the platform stand-in recipient (%s), not "
            "the lead — see docs/contract-change-requests/p3-2-email-recipient-address.md",
            self._dev_recipient,
        )
        return self._dev_recipient

    def _http_poster(self, url: str, json_body: dict, headers: dict):
        import httpx  # local import: keep the module importable with no network dep at rest

        return httpx.post(url, json=json_body, headers=headers, timeout=self._timeout)
