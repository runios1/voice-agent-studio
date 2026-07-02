"""Runnable walkthrough of the tool-registry flow (no network, no secrets).

    python -m backend.tool_registry.demo

Shows, end to end: a tenant connects a calendar via OAuth (fake provider) → the
token is stored ENCRYPTED → the agent's registry books a valid slot (emitting the
event trail) → an out-of-hours slot is REJECTED in code → a different tenant is
DENIED access to the first tenant's connection. This is the behavioral proof of the
workstream for a human reader; the same paths are asserted in the test suite.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from contracts.config_schema.schema import AgentConfig, AgentMeta
from contracts.events.schema import EventType
from backend.tool_registry.connections import ConnectionManager, ConnectionStore
from backend.tool_registry.credentials import EncryptedCredentialStore, generate_key
from backend.tool_registry.errors import GuardrailViolation, NotConnected
from backend.tool_registry.events import InMemoryEventSink
from backend.tool_registry.integrations import MockCalendarClient
from backend.tool_registry.oauth import FakeOAuthProvider
from backend.tool_registry.registry import build_registry

ALICE, BOB = "tenant-alice", "tenant-bob"
PROVIDER = "google_calendar"


def _slot(hour: int, days: int = 1) -> str:
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _config() -> AgentConfig:
    now = datetime.now(timezone.utc)
    cfg = AgentConfig(meta=AgentMeta(id="a1", owner_user_id=ALICE, created_at=now, updated_at=now))
    cfg.automation.calendar.enabled = True
    cfg.automation.email.enabled = False
    return cfg


async def main() -> None:
    credentials = EncryptedCredentialStore(key=generate_key())
    connections = ConnectionStore()
    manager = ConnectionManager({PROVIDER: FakeOAuthProvider(PROVIDER)}, connections, credentials)
    sink = InMemoryEventSink()
    calendar_client = MockCalendarClient()

    print("1. Alice connects her calendar via OAuth...")
    url = manager.begin_connect(ALICE, PROVIDER, ["calendar.events"], "https://app/cb")
    state = parse_qs(urlparse(url).query)["state"][0]
    conn = await manager.complete_connect(state, code="oauth-code")
    stored = credentials._by_ref[conn.connection_ref].ciphertext
    print(f"   -> connection_ref={conn.connection_ref[:12]}...  token at rest is ciphertext: {stored[:16]}...\n")

    reg = build_registry(_config(), connections, credentials, sink=sink, calendar_client=calendar_client)

    print("2. Book a valid in-hours slot:")
    res = await reg.execute("calendar", {"start_iso": _slot(15)}, ALICE)
    print(f"   -> {res}")
    print(f"   -> events emitted: {[e.type.value for e in sink.events]}\n")

    print("3. Try an out-of-hours slot (22:00) — guardrail should reject in code:")
    try:
        await reg.execute("calendar", {"start_iso": _slot(22)}, ALICE)
    except GuardrailViolation as e:
        print(f"   -> REJECTED: {e.message}")
    print(f"   -> guardrail trips on the stream: {len(sink.of_type(EventType.GUARDRAIL_TRIPPED))}\n")

    print("4. Bob (no connection) tries to use Alice's agent — cross-tenant blocked:")
    try:
        await reg.execute("calendar", {"start_iso": _slot(15)}, BOB)
    except NotConnected as e:
        print(f"   -> DENIED: {e.message}")
    print(f"\n   calendar bookings that actually happened: {len(calendar_client.booked)} (only the valid one)")


if __name__ == "__main__":
    asyncio.run(main())
