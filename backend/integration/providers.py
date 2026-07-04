"""Provider client selection — mock vs. real, decided by the environment, in ONE place.

The tool handlers (calendar/email) call their provider client behind a fixed method
signature (D9). This module is the only spot that chooses which client that is:

  * no provider env keys      -> the in-repo mock clients (dev / CI): no network, records
                                 what it would have done so the audit trail still shows it.
  * GOOGLE_OAUTH_CLIENT_ID    -> the real Google Calendar client (task 6).
  * RESEND_API_KEY            -> the real Resend email client (task 7).

Keeping the switch here (not scattered) means `runtime.py` can ask ONE question —
`using_mock_clients()` — to decide whether to seed a dev placeholder connection.
"""

from __future__ import annotations

import os

from backend.tool_registry.integrations import MockCalendarClient, MockEmailClient


def calendar_is_real() -> bool:
    return bool(os.getenv("GOOGLE_OAUTH_CLIENT_ID"))


def email_is_real() -> bool:
    return bool(os.getenv("RESEND_API_KEY"))


def using_mock_clients() -> bool:
    """True when NEITHER real provider is configured — the dev/CI default."""
    return not (calendar_is_real() or email_is_real())


def build_calendar_client():
    """The calendar client the CalendarHandler runs against (same method signatures)."""
    if calendar_is_real():
        from backend.integration.google_calendar import GoogleCalendarClient

        return GoogleCalendarClient()
    return MockCalendarClient()


def build_email_client():
    """The email client the EmailHandler runs against (same method signatures)."""
    if email_is_real():
        from backend.integration.resend_email import ResendEmailClient

        return ResendEmailClient()
    # Mirror the real client's platform template catalog into the mock so a template id
    # (e.g. the seeded `booking_confirmation`) resolves in dev/unconfigured too — an
    # empty mock template store made the confirmation send fail with "No such template".
    from backend.integration.resend_email import _DEFAULT_TEMPLATES
    from backend.tool_registry.integrations import EmailTemplate as MockTemplate

    templates = [
        MockTemplate(t.template_id, t.subject, t.body, list(t.links))
        for t in _DEFAULT_TEMPLATES.values()
    ]
    return MockEmailClient(templates)
