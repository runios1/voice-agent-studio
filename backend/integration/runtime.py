"""The real voice-runtime stack: a `CallEngine`, per-agent tool registries, and the
shared per-tenant tool stores — assembled once and reused across every call.

This is the seam between the orchestrator (which knows campaigns/leads) and the tools
(which know calendars/inboxes). The pieces:

  * `ToolStack` — the shared, tenant-scoped `ConnectionStore` + `EncryptedCredentialStore`
    plus the provider CLIENTS (mock in dev, real behind env). It builds the per-agent
    `InMemoryToolRegistry` from a config (only ENABLED automation yields a live tool).
  * `build_call_engine` — the screened Gemini voice `CallEngine`, reusing the studio's
    already-screened `ModelWrapper` so we don't build/screen Gemini twice.
  * `make_transport_factory` — RetellTransport when RETELL_API_KEY is set, else a scripted
    MockVoiceTransport so a campaign still runs end-to-end (dial -> outcome -> events)
    before a phone account exists.

Provider clients default to the in-repo mocks; `backend/integration/providers.py` swaps in
the real Google Calendar / Resend clients behind the SAME signatures when their env keys are
present (D9 posture — no handler change).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("voice_agent_studio.runtime")

from contracts.config_schema.schema import AgentConfig
from contracts.tool_registry.interface import Connection
from contracts.voice_runtime.interface import CallTransport
from contracts.campaign.model import Lead
from contracts.model_wrapper.interface import ModelWrapper

from backend.voice_runtime.engine import CallEngine
from backend.voice_runtime.events import EventSink
from backend.voice_runtime.transports import MockVoiceTransport, RetellTransport

from backend.tool_registry.catalog import GOOGLE_CALENDAR, GMAIL
from backend.tool_registry.connections import ConnectionManager, ConnectionStore
from backend.tool_registry.credentials import EncryptedCredentialStore, generate_key
from backend.tool_registry.oauth import (
    PROVIDER_SPECS,
    FakeOAuthProvider,
    GoogleOAuthProvider,
    OAuthProvider,
)
from backend.tool_registry.registry import InMemoryToolRegistry, build_registry

from backend.integration.providers import (
    build_calendar_client,
    build_email_client,
    calendar_is_real,
    using_mock_clients,
)


# A canned lead so a mock (no-Retell) campaign call still exercises the whole path —
# disclosure, an objection, then a booking ask — and classifies to a real outcome.
_MOCK_LEAD_SCRIPT = [
    "Hello?",
    "Okay, what's this about?",
    "Sure, Tuesday afternoon works. Go ahead and book it.",
]


@dataclass
class ToolStack:
    """Shared per-tenant tool infrastructure. One instance for the whole app; the
    registry it builds is per-agent (per config), because enabled tools + guardrails
    differ per agent."""

    connections: ConnectionStore
    credentials: EncryptedCredentialStore
    calendar_client: object
    email_client: object
    connection_manager: ConnectionManager

    def registry_for(self, config: AgentConfig, sink: EventSink) -> InMemoryToolRegistry:
        """The registry an agent actually exposes: only ENABLED automation blocks yield
        a live, guardrailed tool (structural denial, as in Phase 1)."""
        return build_registry(
            config,
            self.connections,
            self.credentials,
            sink=sink,
            calendar_client=self.calendar_client,
            email_client=self.email_client,
        )

    def ensure_dev_connections(self, tenant_id: str) -> None:
        """Dev convenience: seed a calendar + email Connection (and a placeholder token)
        for a tenant so the MOCK provider clients can run before real OAuth is wired.

        No-op once a real connection exists for the provider, so this never clobbers a
        token minted by the real OAuth flow. Guarded to the mock clients: with real
        clients, a real OAuth connection is required (we don't fake a Google token)."""
        if not using_mock_clients():
            return
        for provider in (GOOGLE_CALENDAR, GMAIL):
            if self.connections.for_provider(tenant_id, provider) is not None:
                continue
            ref = f"dev-{provider}-{tenant_id}"
            self.connections.add(
                Connection(
                    tenant_id=tenant_id,
                    provider=provider,
                    connection_ref=ref,
                    scopes=[],
                )
            )
            # A non-empty token: the mock clients only assert it's present (a real 401
            # shape); the real clients never see this branch.
            self.credentials.put(
                tenant_id, ref, provider, access_token="dev-placeholder-token"
            )


async def _httpx_post(url: str, data: dict) -> dict:
    """The real, network-touching `HttpPost` injected into `GoogleOAuthProvider` —
    `httpx` is imported lazily so this module carries no SDK/network cost until an
    actual code exchange runs (D8)."""
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, data=data)
    resp.raise_for_status()
    return resp.json()


def _build_oauth_providers() -> dict[str, OAuthProvider]:
    """One provider per catalog entry (`PROVIDER_SPECS`): the real Google flow when
    `GOOGLE_OAUTH_CLIENT_ID` is set (both `google_calendar` and `gmail` share Google's
    endpoints/client), else the no-network `FakeOAuthProvider` (dev/CI)."""
    if calendar_is_real():
        return {
            name: GoogleOAuthProvider(spec, _httpx_post)
            for name, spec in PROVIDER_SPECS.items()
        }
    return {name: FakeOAuthProvider(name) for name in PROVIDER_SPECS}


def build_tool_stack() -> ToolStack:
    """Assemble the shared tool stores + provider clients from the environment.

    The credential store reads `TOOL_REGISTRY_ENC_KEY` and refuses to run in plaintext.
    For a dev boot without one we mint an EPHEMERAL key (documented dev-bootstrap use of
    `generate_key`) so the app starts — with a warning, since stored tokens then don't
    survive a restart. Production MUST set the env key."""
    enc_key = os.getenv("TOOL_REGISTRY_ENC_KEY")
    if not enc_key:
        enc_key = generate_key()
        log.warning(
            "TOOL_REGISTRY_ENC_KEY not set — using an ephemeral credential key; stored "
            "tool tokens will NOT survive a restart. Set TOOL_REGISTRY_ENC_KEY in prod."
        )
    connections = ConnectionStore()
    credentials = EncryptedCredentialStore(key=enc_key)
    return ToolStack(
        connections=connections,
        credentials=credentials,
        calendar_client=build_calendar_client(),
        email_client=build_email_client(),
        connection_manager=ConnectionManager(
            _build_oauth_providers(), connections, credentials
        ),
    )


def build_call_engine(model: ModelWrapper, sink: EventSink) -> CallEngine:
    """The voice `CallEngine`, reusing the studio's already-screened wrapper. The engine
    selects the `voice` model tier (Gemini Flash Live) per config."""
    return CallEngine(model, sink, model_tier="voice")


def make_transport_factory():
    """Return a `TransportFactory`. Retell when configured (real outbound phone), else a
    scripted mock so campaigns run end-to-end without a telephony account."""
    api_key = os.getenv("RETELL_API_KEY")
    agent_number = os.getenv("RETELL_FROM_NUMBER")

    class _Factory:
        def create(self, lead: Lead) -> CallTransport:
            if api_key:
                return RetellTransport(api_key=api_key, agent_number=agent_number)
            return MockVoiceTransport(list(_MOCK_LEAD_SCRIPT))

    return _Factory()


def retell_configured() -> bool:
    return bool(os.getenv("RETELL_API_KEY"))
