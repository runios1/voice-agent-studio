"""ConfigGate — THE source-agnostic enforcement boundary (D-security).

Pure and in-memory: given a config + a single {path, value} mutation, it returns
a new config or raises a typed GateError. It performs NO persistence and calls NO
models — it only reaches WS5 through the injected ScreeningPort. Builder patches,
manual PATCHes, and forged requests all funnel through `check_and_apply`; there
is exactly one code path, so the security check cannot be bypassed by source.

Order of checks (mirrors backend/config_gate/README.md):
  1. schema / type validation — apply the value; malformed => `validation`.
  2. locked-path rejection    — platform-locked or system-managed => `locked_path`.
  3. free-text screening      — prose fields via WS5 => `screening_blocked`, or
                                 accepted-with-flag for merely-odd content.
On accept it recomputes `meta.status` (completeness) so READY-ness is always
consistent with content. Version bump + timestamps are a persistence concern and
belong to the repository/service, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from pydantic import ValidationError

from contracts.config_schema.schema import AgentConfig
from backend.config_gate import policy
from backend.config_gate.completeness import evaluate_status
from backend.config_gate.errors import ErrorKind, GateError
from backend.config_gate.paths import (
    InvalidPath,
    apply_patch,
    summarize_validation_error,
)
from backend.config_gate.screening import ScreeningPort, ScreeningResult


@dataclass
class Notice:
    """A non-fatal message the caller may surface conversationally (a `notice`)."""

    kind: str          # e.g. "screening_flagged"
    path: str
    message: str


@dataclass
class GateOutcome:
    """Result of an accepted mutation. `flag` is set iff screening flagged it."""

    config: AgentConfig
    path: str
    value: Any
    flag: Optional[Notice] = None


def _collect_strings(value: Any) -> list[str]:
    """All string leaves inside a patch value (handles lists/dicts like objections)."""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_collect_strings(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out.extend(_collect_strings(v))
    return out


class ConfigGate:
    def __init__(self, screener: ScreeningPort):
        self._screener = screener

    def check_and_apply(self, config: AgentConfig, path: str, value: Any) -> GateOutcome:
        # 1) schema / type validation (also catches unknown paths).
        try:
            candidate = apply_patch(config, path, value)
        except InvalidPath as exc:
            raise GateError(ErrorKind.VALIDATION, f"I don't recognize that field ({path}).", path) from exc
        except ValidationError as exc:
            raise GateError(ErrorKind.VALIDATION, summarize_validation_error(exc), path) from exc

        # 2) locked-path rejection (platform-locked or system-managed sub-tree).
        if policy.is_locked(path):
            raise GateError(
                ErrorKind.LOCKED_PATH,
                "That's set by the platform and can't be changed here.",
                path,
            )

        # 3) free-text screening on prose fields (delegated to WS5).
        flag: Optional[Notice] = None
        if policy.is_prose(path):
            for text in _collect_strings(value):
                result: ScreeningResult = self._screener.screen_text(path, text)
                if result.verdict == "blocked":
                    raise GateError(ErrorKind.SCREENING_BLOCKED, result.message, path)
                if result.verdict == "flagged" and flag is None:
                    flag = Notice(kind=ErrorKind.SCREENING_FLAGGED.value, path=path, message=result.message)

        # Accept: recompute completeness so status is always consistent with content.
        candidate.meta.status = evaluate_status(candidate)
        return GateOutcome(config=candidate, path=path, value=value, flag=flag)
