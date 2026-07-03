"""Shared fixtures for the orchestrator tests.

Time is fully controlled: `clock` is a ManualClock and `fast_sleep` advances it
instead of really sleeping (then yields so pending call-tasks run). That makes every
time-dependent behaviour — calling windows, backoff, rate limiting, retries — run in
microseconds and deterministically.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Callable

import pytest

from contracts.config_schema.schema import AgentConfig, AgentMeta
from backend.orchestrator.clock import ManualClock
from backend.orchestrator.events import InMemoryEventSink
from backend.orchestrator.mocks import InMemoryConfigSource, ScriptedDialer
from backend.orchestrator.repository import InMemoryOrchestratorRepository
from backend.orchestrator.service import LeadSpec, OrchestratorService

TENANT = "tenant-alice"
OTHER = "tenant-bob"
AGENT_ID = "agent-1"


def make_config(agent_id: str = AGENT_ID, owner: str = TENANT) -> AgentConfig:
    now = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    return AgentConfig(
        meta=AgentMeta(id=agent_id, owner_user_id=owner, created_at=now, updated_at=now)
    )


@pytest.fixture
def clock() -> ManualClock:
    # 10:00 UTC — inside the default 8–20 calling window.
    return ManualClock(datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc))


@pytest.fixture
def fast_sleep(clock: ManualClock) -> Callable:
    async def _sleep(seconds: float) -> None:
        if seconds > 0:
            clock.advance(seconds)
        await asyncio.sleep(0)  # yield so in-flight call-tasks make progress

    return _sleep


@pytest.fixture
def repo() -> InMemoryOrchestratorRepository:
    return InMemoryOrchestratorRepository()


@pytest.fixture
def sink() -> InMemoryEventSink:
    return InMemoryEventSink()


@pytest.fixture
def config_source() -> InMemoryConfigSource:
    src = InMemoryConfigSource()
    src.add(TENANT, make_config())
    return src


@pytest.fixture
def dialer() -> ScriptedDialer:
    return ScriptedDialer()  # all calls QUALIFIED by default


@pytest.fixture
def service(repo, sink, config_source, dialer, clock, fast_sleep) -> OrchestratorService:
    return OrchestratorService(
        config_source=config_source,
        dialer=dialer,
        repo=repo,
        sink=sink,
        clock=clock,
        sleep=fast_sleep,
    )


def leads(n: int) -> list[LeadSpec]:
    return [LeadSpec(phone=f"+1555000{i:04d}", display_name=f"Lead {i}") for i in range(n)]


async def await_state(repo, lead_id: str, tenant: str, state, tries: int = 500) -> None:
    """Yield until a lead reaches `state` (used to catch an in-flight DIALING lead)."""
    for _ in range(tries):
        lead = repo.get_lead(lead_id, tenant)
        if lead is not None and lead.state == state:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"lead {lead_id} never reached {state}")
