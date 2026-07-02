"""Completeness model (D12) — when is an agent deploy-ready?

The `required_for_ready` fields in FIELD_POLICY *are* the completeness model the
builder interviews toward. When every one is satisfied, `meta.status` flips to
READY. This module is that evaluation, and nothing else decides READY-ness.

"Satisfied" is intentionally strict-but-simple: a field counts as filled when it
is present and non-empty — None, "", "  ", and [] do NOT count. Enum fields carry
a concrete value only once chosen; those that default to None (e.g. voicemail.action)
stay unsatisfied until answered, so the builder genuinely interviews toward them.
"""

from __future__ import annotations

from typing import Any

from contracts.config_schema.field_policy import FIELD_POLICY
from contracts.config_schema.schema import AgentConfig, AgentStatus
from backend.config_gate.paths import InvalidPath, get_at

_REQUIRED_PATHS: list[str] = [p.path for p in FIELD_POLICY if p.required_for_ready]


def _is_satisfied(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True  # bools, ints, enums with a concrete value


def missing_required(config: AgentConfig) -> list[str]:
    """The required paths not yet satisfied — what the builder still needs to ask."""
    missing: list[str] = []
    for path in _REQUIRED_PATHS:
        try:
            value = get_at(config, path)
        except InvalidPath:
            missing.append(path)
            continue
        if not _is_satisfied(value):
            missing.append(path)
    return missing


def evaluate_status(config: AgentConfig) -> AgentStatus:
    return AgentStatus.READY if not missing_required(config) else AgentStatus.DRAFT
