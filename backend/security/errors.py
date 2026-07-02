"""
Exceptions for the screening layer.

`ScreeningBlocked` is the one that crosses a boundary: the `ScreeningModelWrapper`
raises it when in/out content is hard-blocked, so the caller (builder / runtime
loop) can turn it into the API's conversational `notice` instead of a stack trace
(D-reliability). It carries everything needed to build the contract's typed error.
"""

from __future__ import annotations

from .models import ERROR_KIND_BLOCKED, Direction, Finding


class ScreeningBlocked(Exception):
    """Raised when content is hard-blocked by the screening layer.

    Maps to the API error shape `{"error": {"kind": "screening_blocked", ...}}`.
    The message is user-facing and MUST stay conversational — never leak internals.
    """

    kind = ERROR_KIND_BLOCKED

    def __init__(
        self,
        message: str,
        *,
        direction: Direction,
        findings: list[Finding] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.direction = direction
        self.findings = findings or []

    @property
    def categories(self) -> list[str]:
        return [f.category.value for f in self.findings]

    def to_api_error(self, path: str | None = None) -> dict:
        """Render the contract's typed error body (contracts/api/api_contract.md)."""
        err: dict = {"kind": self.kind, "message": self.message}
        if path is not None:
            err["path"] = path
        return {"error": err}
