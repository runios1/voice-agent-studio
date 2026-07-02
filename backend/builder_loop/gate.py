"""The config-gate seam that the builder loop consumes.

The gate (workstream 2) is THE source-agnostic enforcement boundary (D-security):
every mutation — builder patch, manual edit, or forged request — passes the same
checks. The builder loop NEVER writes the config directly; it always goes through
this seam (see backend/builder_loop/README.md boundaries).

This module defines only the *seam* the builder depends on:
  * `Gate` — the Protocol the builder calls (apply a patch, read the config);
  * `Patch` / `GateAccepted` — the accepted-mutation shapes;
  * `GateError` — the typed rejection, mirroring the error taxonomy in
    contracts/api/api_contract.md.

The real gate (WS2) supplies the concrete implementation at integration time; a
faithful in-memory `FakeGate` for tests lives in `testing.py`. Both honor this
seam. Dotted-path helpers used by both live here too.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

# Contracts are namespace packages at the repo root (no __init__.py).
from contracts.config_schema.schema import AgentConfig, AgentStatus

# The rejection kinds the gate may raise. Kept identical to the API error shape so
# a NoticeEvent can carry the kind straight through to the UI.
GateErrorKind = str  # "locked_path" | "validation" | "screening_blocked"
#                    | "screening_flagged" | "rate_limited"


class GateError(Exception):
    """A rejected mutation. The builder converts this into a conversational
    `notice` (never a stack trace — D-reliability)."""

    def __init__(self, kind: GateErrorKind, message: str, path: Optional[str] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.path = path


@dataclass
class Patch:
    """An accepted config mutation."""

    path: str
    value: Any


@dataclass
class GateAccepted:
    """What the gate returns on a successful mutation. `status` is the gate's
    AUTHORITATIVE completeness verdict after applying the patch; the builder only
    reflects it (it does not decide READY itself)."""

    patch: Patch
    version: int
    status: AgentStatus
    status_changed: bool


@runtime_checkable
class Gate(Protocol):
    """The narrow surface the builder needs from the gate.

    Reads (`get_config`) so it can compute interview gaps and build list-append
    patches; writes (`apply_patch`) as the ONLY door to mutate the config. Both are
    tenant-scoped in the real gate by code (never by a prompt) — the builder passes
    an opaque agent_id and never a client-supplied owner id (D-security)."""

    def get_config(self, agent_id: str) -> AgentConfig: ...

    def apply_patch(self, agent_id: str, path: str, value: Any) -> GateAccepted: ...


# --------------------------------------------------------------------------- #
# Dotted-path helpers (shared by FakeGate and the loop's list-append handlers)
# --------------------------------------------------------------------------- #
def get_by_path(data: dict, path: str) -> Any:
    """Read a value at a dotted path from a plain dict (a model_dump)."""
    cur: Any = data
    for part in path.split("."):
        cur = cur[part]
    return cur


def set_by_path(data: dict, path: str, value: Any) -> None:
    """Set a value at a dotted path in a plain dict, in place. Intermediate nodes
    are assumed to exist (the config is always fully-formed with defaults)."""
    parts = path.split(".")
    cur: Any = data
    for part in parts[:-1]:
        cur = cur[part]
    cur[parts[-1]] = value
