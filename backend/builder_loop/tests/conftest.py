"""Test setup for the builder loop.

The three frozen contracts live at the repo root as namespace packages (no
__init__.py). Put the repo root on sys.path so `contracts.*` and `backend.*`
import cleanly no matter where pytest is launched from.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.config_schema.schema import AgentConfig, AgentMeta  # noqa: E402
from contracts.model_wrapper.interface import ModelResponse, ToolCall  # noqa: E402

from backend.builder_loop.loop import BuilderLoop  # noqa: E402
from backend.builder_loop.session import InMemorySessionStore  # noqa: E402
from backend.builder_loop.testing import FakeGate, ScriptedModel, Screener  # noqa: E402

AGENT_ID = "agent-1"


@pytest.fixture
def fresh_config() -> AgentConfig:
    now = datetime.now(timezone.utc)
    return AgentConfig(
        meta=AgentMeta(id=AGENT_ID, owner_user_id="user-1", created_at=now, updated_at=now)
    )


def make_loop(
    script: list[ModelResponse],
    config: AgentConfig,
    screener: Optional[Screener] = None,
) -> tuple[BuilderLoop, FakeGate]:
    gate = FakeGate(config, screener=screener)
    loop = BuilderLoop(model=ScriptedModel(script), gate=gate, sessions=InMemorySessionStore())
    return loop, gate


def resp(text: str = "", calls: Optional[list[ToolCall]] = None) -> ModelResponse:
    return ModelResponse(text=text, tool_calls=calls or [])


def tc(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(name=name, arguments=arguments)


def collect(loop: BuilderLoop, text: str, agent_id: str = AGENT_ID) -> list[Any]:
    """Run one turn to completion and return the emitted events."""

    async def _run() -> list[Any]:
        return [event async for event in loop.run_turn(agent_id, text)]

    return asyncio.run(_run())
