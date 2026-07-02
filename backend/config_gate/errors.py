"""Typed error taxonomy — the contract's error shape (D-reliability).

The API contract (`contracts/api/api_contract.md`) defines the wire shape:

    { "error": { "kind": "...", "path": "...", "message": "..." } }

with kinds `locked_path | validation | screening_blocked | screening_flagged |
rate_limited`. This module is the single place that produces that shape, so the
UI never sees a stack trace.

NOTE (contract gap): WS2 additionally needs `conflict` (optimistic-concurrency
loser) and `not_found` (tenant-scoped miss). These are NOT in the frozen kind
list; a change request is filed at docs/contract-change-requests/ws2.md. They are
declared here (not by editing the contract) and clearly flagged until ratified.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorKind(str, Enum):
    # --- in the frozen api_contract ---
    LOCKED_PATH = "locked_path"            # tried to change a platform-locked field
    VALIDATION = "validation"              # bad type / unknown path / schema violation
    SCREENING_BLOCKED = "screening_blocked"  # free-text hit a locked-guardrail domain
    SCREENING_FLAGGED = "screening_flagged"  # merely-odd content (accepted-but-flagged)
    RATE_LIMITED = "rate_limited"

    # --- WS2 extensions, pending contract ratification (see ws2.md CCR) ---
    CONFLICT = "conflict"                  # expected_version stale; concurrent edit won
    NOT_FOUND = "not_found"                # no such agent for this authed owner


class GateError(Exception):
    """A rejection with a client-safe, conversational message.

    Carries everything needed to render the contract error shape and to pick an
    HTTP status. Never leaks internals — `message` is human-friendly by design.
    """

    def __init__(self, kind: ErrorKind, message: str, path: Optional[str] = None):
        self.kind = kind
        self.message = message
        self.path = path
        super().__init__(f"{kind.value}: {message}")

    def to_dict(self) -> dict:
        """The exact wire shape from the API contract."""
        return {"error": {"kind": self.kind.value, "path": self.path, "message": self.message}}

    # Advisory HTTP status per kind; the router uses this so mapping lives in one place.
    _STATUS = {
        ErrorKind.LOCKED_PATH: 403,
        ErrorKind.VALIDATION: 422,
        ErrorKind.SCREENING_BLOCKED: 422,
        ErrorKind.SCREENING_FLAGGED: 422,
        ErrorKind.RATE_LIMITED: 429,
        ErrorKind.CONFLICT: 409,
        ErrorKind.NOT_FOUND: 404,
    }

    @property
    def http_status(self) -> int:
        return self._STATUS.get(self.kind, 400)
