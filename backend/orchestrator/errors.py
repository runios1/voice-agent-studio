"""Typed errors for the orchestrator's control surface.

Mirrors the calm-failure posture of the rest of the backend (D-reliability): the
control API translates these into a `{error: {kind, message}}` shape, never a stack
trace. Tenant isolation follows the config-gate convention — a campaign that isn't
yours reads as NOT_FOUND, so existence is never leaked (D-security).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ErrorKind(str, Enum):
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"          # e.g. illegal state transition
    VALIDATION = "validation"      # e.g. an envelope that widens a locked bound


_HTTP = {
    ErrorKind.NOT_FOUND: 404,
    ErrorKind.CONFLICT: 409,
    ErrorKind.VALIDATION: 400,
}


class OrchestratorError(Exception):
    def __init__(self, kind: ErrorKind, message: str, ref: Optional[str] = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.ref = ref

    @property
    def http_status(self) -> int:
        return _HTTP[self.kind]

    def to_dict(self) -> dict:
        return {"error": {"kind": self.kind.value, "message": self.message, "ref": self.ref}}


class NotFound(OrchestratorError):
    def __init__(self, ref: str):
        super().__init__(ErrorKind.NOT_FOUND, "No such campaign.", ref)


class IllegalTransition(OrchestratorError):
    def __init__(self, message: str, ref: Optional[str] = None):
        super().__init__(ErrorKind.CONFLICT, message, ref)


class EnvelopeViolation(OrchestratorError):
    def __init__(self, message: str):
        super().__init__(ErrorKind.VALIDATION, message)
