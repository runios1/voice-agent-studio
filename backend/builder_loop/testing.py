"""Test doubles for the builder loop.

WS3 depends on two things not yet merged: the config gate (WS2) and a concrete
ModelWrapper (WS6). Per the dispatch protocol, we MOCK them here against the frozen
contracts:

  * `FakeGate` — a faithful in-memory stand-in for WS2's gate. It enforces the
    parts the builder actually leans on: locked-path rejection (via FIELD_POLICY),
    schema/type validation (via AgentConfig), version bump, and the authoritative
    completeness status flip. It also exposes an injectable `screener` hook so the
    "free-text touching a locked-guardrail domain -> blocked" path (delegated to
    WS5 in the real gate) can be exercised. It does NOT implement WS2's real
    responsibilities (Postgres persistence, versioned history/undo, tenant
    isolation by user id) — those are out of WS3's boundary.

  * `ScriptedModel` — a ModelWrapper whose `complete()` returns a pre-scripted
    sequence of ModelResponses, so a conversation is fully deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional

from pydantic import ValidationError

from contracts.config_schema.field_policy import FIELD_POLICY, Mutability
from contracts.config_schema.schema import AgentConfig
from contracts.model_wrapper.interface import (
    Message,
    ModelResponse,
    ModelWrapper,
    ToolDef,
)

from .completeness import evaluate_status
from .gate import GateAccepted, GateError, Patch, set_by_path

# A screener returns "ok" | "flag" | "block" for a prose value at a path.
Screener = Callable[[str, str], str]


def _is_locked(path: str) -> bool:
    """Locked if the most specific matching policy row is LOCKED, or if the path is
    an ancestor of any locked field (so patching a whole subtree can't sneak past)."""
    best: Optional[Any] = None
    for fp in FIELD_POLICY:
        if path == fp.path or path.startswith(fp.path + "."):
            if best is None or len(fp.path) > len(best.path):
                best = fp
    if best is not None and best.mutability == Mutability.LOCKED:
        return True
    return any(
        fp.mutability == Mutability.LOCKED and fp.path.startswith(path + ".")
        for fp in FIELD_POLICY
    )


class FakeGate:
    """In-memory config gate honoring the `Gate` seam. See module docstring."""

    def __init__(self, config: AgentConfig, screener: Optional[Screener] = None) -> None:
        self._configs: dict[str, AgentConfig] = {config.meta.id: config}
        self._screener = screener

    def get_config(self, agent_id: str) -> AgentConfig:
        return self._configs[agent_id]

    def apply_patch(self, agent_id: str, path: str, value: Any) -> GateAccepted:
        config = self._configs[agent_id]

        # 1. Locked-path rejection (server-side; never trust the caller — D-security).
        if _is_locked(path):
            raise GateError(
                kind="locked_path",
                message=(
                    "That's a platform guardrail I can't change — it's locked to keep "
                    "your calls compliant."
                ),
                path=path,
            )

        # 2. Free-text screening (delegated to WS5 in the real gate; hook here).
        if self._screener is not None and isinstance(value, str):
            verdict = self._screener(path, value)
            if verdict == "block":
                raise GateError(
                    kind="screening_blocked",
                    message="I can't set that — it conflicts with a required safety rule.",
                    path=path,
                )
            if verdict == "flag":
                raise GateError(
                    kind="screening_flagged",
                    message="That wording looked off, so I held it. Want to rephrase?",
                    path=path,
                )

        # 3. Schema/type validation via a full round-trip through AgentConfig.
        data = config.model_dump()
        try:
            set_by_path(data, path, value)
        except (KeyError, TypeError):
            raise GateError(kind="validation", message=f"Unknown config path '{path}'.", path=path)
        try:
            new_config = AgentConfig.model_validate(data)
        except ValidationError:
            raise GateError(
                kind="validation",
                message="That value didn't fit the field — could you say it differently?",
                path=path,
            )

        # 4. Accept: bump version, recompute authoritative status, persist.
        previous_status = config.meta.status
        new_config.meta.version = config.meta.version + 1
        new_config.meta.updated_at = datetime.now(timezone.utc)
        new_config.meta.status = evaluate_status(new_config)
        self._configs[agent_id] = new_config

        return GateAccepted(
            patch=Patch(path=path, value=value),
            version=new_config.meta.version,
            status=new_config.meta.status,
            status_changed=new_config.meta.status != previous_status,
        )


class ScriptedModel(ModelWrapper):
    """A ModelWrapper that plays back a fixed list of ModelResponses. Each call to
    `complete()` pops the next scripted response; records inputs for assertions."""

    def __init__(self, script: list[ModelResponse]) -> None:
        self._script = list(script)
        self.calls: list[list[Message]] = []

    async def complete(
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        response_schema: Optional[dict[str, Any]] = None,
        model_tier: str = "frontier",
    ) -> ModelResponse:
        self.calls.append(list(messages))
        if not self._script:
            return ModelResponse(text="", tool_calls=[])
        return self._script.pop(0)

    async def stream(  # type: ignore[override]
        self,
        messages: list[Message],
        tools: Optional[list[ToolDef]] = None,
        model_tier: str = "frontier",
    ) -> AsyncIterator[str]:
        # The builder uses complete() (tool-calling); stream() is unused here.
        if False:  # pragma: no cover - present only to satisfy the interface
            yield ""
        raise NotImplementedError("ScriptedModel does not stream.")
