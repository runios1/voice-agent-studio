"""Workstream 2 — Config gate + persistence.

THE source-agnostic, server-side enforcement boundary (D-security). Every config
mutation — builder tool-call, manual PATCH, or a forged request — passes through
the SAME gate. The LLM's triage is UX; this is the security boundary.

Public surface:
  * `ConfigGate`      — pure, in-memory enforcement (validate → lock → screen).
  * `AgentService`    — gate + persistence: create / get / list / patch / revert.
  * `ConfigRepository`, `InMemoryConfigRepository`, `PostgresConfigRepository`.
  * `GateError`, `ErrorKind` — the typed error taxonomy (contract error shape).
  * `ScreeningPort`   — the seam to WS5 (mocked here).
"""

from __future__ import annotations

from backend.config_gate.errors import ErrorKind, GateError
from backend.config_gate.gate import ConfigGate, GateOutcome, Notice
from backend.config_gate.repository import (
    ConfigRepository,
    InMemoryConfigRepository,
    StoredVersion,
)
from backend.config_gate.screening import (
    MockScreeningAdapter,
    ScreeningPort,
    ScreeningResult,
)
from backend.config_gate.service import AgentService

__all__ = [
    "ConfigGate",
    "GateOutcome",
    "Notice",
    "AgentService",
    "ConfigRepository",
    "InMemoryConfigRepository",
    "StoredVersion",
    "GateError",
    "ErrorKind",
    "ScreeningPort",
    "ScreeningResult",
    "MockScreeningAdapter",
]
