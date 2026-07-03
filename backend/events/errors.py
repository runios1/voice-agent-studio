"""Typed errors for the event backbone — same posture as the config gate: a caller
sees a calm, typed error, never a stack trace (D-reliability)."""

from __future__ import annotations

from typing import Optional


class EventError(Exception):
    """Base for event-backbone errors."""

    kind = "event_error"
    http_status = 400

    def __init__(self, message: str, detail: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"error": {"kind": self.kind, "message": self.message, "detail": self.detail}}


class EventValidationError(EventError):
    """A payload failed its per-type schema. Raised at emit BEFORE persistence, so a
    malformed event never enters the append-only log."""

    kind = "event_validation"
    http_status = 422
