"""Shared fixtures for the tool-registry tests.

Everything here is in-memory and network-free: a Fernet key generated per run, a
fake OAuth provider, mock calendar/email clients, and an `InMemoryEventSink` so
tests can assert on the emitted event trail. Two tenant ids are provided so the
isolation tests have a "self" and an "other".
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts.config_schema.schema import AgentConfig, AgentMeta
from backend.tool_registry.connections import ConnectionManager, ConnectionStore
from backend.tool_registry.credentials import EncryptedCredentialStore, generate_key
from backend.tool_registry.events import InMemoryEventSink
from backend.tool_registry.integrations import EmailTemplate, MockCalendarClient, MockEmailClient
from backend.tool_registry.oauth import FakeOAuthProvider

TENANT = "tenant-alice"
OTHER = "tenant-bob"
REDIRECT = "https://app.test/oauth/callback"

# The two providers our v1 catalog needs a connection for.
CALENDAR_PROVIDER = "google_calendar"
EMAIL_PROVIDER = "gmail"


def make_config(
    *,
    calendar_enabled: bool = True,
    email_enabled: bool = True,
    template_ids: list[str] | None = None,
    allowed_link_domains: list[str] | None = None,
    booking_window_days: int = 14,
    calling_hours: tuple[int, int] = (8, 20),
) -> AgentConfig:
    now = datetime.now(timezone.utc)
    cfg = AgentConfig(
        meta=AgentMeta(id="agent-1", owner_user_id=TENANT, created_at=now, updated_at=now)
    )
    cfg.automation.calendar.enabled = calendar_enabled
    cfg.automation.calendar.booking_window_days = booking_window_days
    cfg.automation.email.enabled = email_enabled
    cfg.automation.email.template_ids = template_ids or []
    cfg.guardrails.allowed_link_domains = allowed_link_domains or []
    cfg.guardrails.calling_hours.start_hour_local = calling_hours[0]
    cfg.guardrails.calling_hours.end_hour_local = calling_hours[1]
    return cfg


@pytest.fixture
def enc_key() -> str:
    return generate_key()


@pytest.fixture
def credentials(enc_key: str) -> EncryptedCredentialStore:
    return EncryptedCredentialStore(key=enc_key)


@pytest.fixture
def connections() -> ConnectionStore:
    return ConnectionStore()


@pytest.fixture
def sink() -> InMemoryEventSink:
    return InMemoryEventSink()


@pytest.fixture
def manager(credentials, connections) -> ConnectionManager:
    providers = {
        CALENDAR_PROVIDER: FakeOAuthProvider(CALENDAR_PROVIDER),
        EMAIL_PROVIDER: FakeOAuthProvider(EMAIL_PROVIDER),
    }
    return ConnectionManager(providers, connections, credentials)


@pytest.fixture
def calendar_client() -> MockCalendarClient:
    return MockCalendarClient()


@pytest.fixture
def email_client() -> MockEmailClient:
    # One approved template with an allowlistable link; one with an off-allowlist link.
    return MockEmailClient(
        templates=[
            EmailTemplate("confirm", "Your meeting", "See you then.", links=["https://acme.com/confirm"]),
            EmailTemplate("bad-link", "Hi", "Click", links=["https://evil.example/steal"]),
            EmailTemplate("plain", "Hi", "No links here.", links=[]),
        ]
    )
