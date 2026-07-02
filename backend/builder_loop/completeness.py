"""The completeness model — the target the interviewer steers toward (D12).

The `required_for_ready` fields in FIELD_POLICY *are* the completeness model: when
all are satisfied the agent is deploy-ready. This module computes, deterministically
and in CODE (never trusting the model — D-reliability), which required fields are
still empty, so the interviewer can guide the user to fill them.

NOTE on ownership: the config gate (WS2) owns the AUTHORITATIVE status flip that it
persists. The builder uses the SAME logic here only to know what to ask about next;
it reflects the gate's returned status rather than setting it itself.
"""

from __future__ import annotations

from typing import Any

from contracts.config_schema.field_policy import FIELD_POLICY
from contracts.config_schema.schema import AgentConfig, AgentStatus

# Derived from the frozen policy so it can never drift out of sync.
REQUIRED_PATHS: list[str] = [fp.path for fp in FIELD_POLICY if fp.required_for_ready]

# Human phrasing for each required field, so the interviewer's system prompt reads
# like goals ("ask about X") rather than dotted paths. Falls back to the path.
FIELD_DESCRIPTIONS: dict[str, str] = {
    "conversation.persona.role": "who the agent is / its role (e.g. 'an SDR for Acme')",
    "conversation.persona.tone": "the speaking tone (e.g. warm, brisk, consultative)",
    "conversation.opening": "how the agent opens the call — who it is and why it's calling",
    "conversation.voicemail.action": "what to do on voicemail (leave a message, or hang up)",
    "conversation.primary_objective": "the goal of the call (e.g. book a 15-minute discovery call)",
    "conversation.qualification.criteria": "the questions/criteria used to qualify a lead",
}


def _value_at(config: AgentConfig, path: str) -> Any:
    cur: Any = config
    for part in path.split("."):
        cur = getattr(cur, part)
    return cur


def _is_satisfied(value: Any) -> bool:
    """A required field counts as answered when it holds real content."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True  # e.g. a chosen enum/int is a real answer


def remaining_gaps(config: AgentConfig) -> list[str]:
    """The required paths still unfilled, in policy order."""
    return [p for p in REQUIRED_PATHS if not _is_satisfied(_value_at(config, p))]


def evaluate_status(config: AgentConfig) -> AgentStatus:
    """READY iff every required field is satisfied, else DRAFT."""
    return AgentStatus.READY if not remaining_gaps(config) else AgentStatus.DRAFT


def describe_gap(path: str) -> str:
    return FIELD_DESCRIPTIONS.get(path, path)
