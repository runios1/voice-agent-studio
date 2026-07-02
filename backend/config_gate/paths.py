"""Dotted-path get/set into the AgentConfig schema, with type validation.

The whole product speaks in dotted paths ("conversation.persona.tone") — the
builder emits patches at them, the frontend renders fields at them, FIELD_POLICY
keys on them. This module is the one place that resolves a path against the
pydantic schema and applies a value with the schema doing the type-checking.

Design choice: set-then-revalidate. We dump the config to a plain dict, mutate
the single leaf, and re-run `AgentConfig.model_validate` on the whole thing. That
makes malformed values a *pydantic* error at the source (D-reliability) instead
of hand-rolled per-field checks. v1 supports dict-key traversal only (no list
indices like `objections.0.trigger`); the builder sets whole lists, matching
FIELD_POLICY, so this is sufficient — extend deliberately later.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from contracts.config_schema.schema import AgentConfig


class InvalidPath(Exception):
    """Path is malformed or does not resolve against the schema."""


def split_path(path: str) -> list[str]:
    if not isinstance(path, str) or not path:
        raise InvalidPath(f"path must be a non-empty string, got {path!r}")
    parts = path.split(".")
    if any(p == "" for p in parts):
        raise InvalidPath(f"path has an empty segment: {path!r}")
    return parts


def get_at(config: AgentConfig, path: str) -> Any:
    """Return the value at `path`, or raise InvalidPath if it doesn't resolve."""
    node: Any = config.model_dump()
    for seg in split_path(path):
        if isinstance(node, dict) and seg in node:
            node = node[seg]
        else:
            raise InvalidPath(f"path does not resolve: {path!r}")
    return node


def path_exists(config: AgentConfig, path: str) -> bool:
    try:
        get_at(config, path)
        return True
    except InvalidPath:
        return False


def apply_patch(config: AgentConfig, path: str, value: Any) -> AgentConfig:
    """Return a NEW AgentConfig with `value` set at `path`.

    Raises:
        InvalidPath   — path malformed or not a real schema location.
        ValidationError — value is the wrong type for that field (re-raised from
                          pydantic so the gate can map it to a `validation` error).
    """
    parts = split_path(path)
    data = config.model_dump()

    node = data
    for seg in parts[:-1]:
        if isinstance(node, dict) and seg in node and isinstance(node[seg], dict):
            node = node[seg]
        else:
            # Non-existent branch, or attempt to traverse through a leaf / list /
            # un-instantiated (None) submodel — not a settable location in v1.
            raise InvalidPath(f"path does not resolve: {path!r}")

    last = parts[-1]
    if not isinstance(node, dict) or last not in node:
        raise InvalidPath(f"path does not resolve: {path!r}")

    node[last] = value
    return AgentConfig.model_validate(data)  # may raise ValidationError


def summarize_validation_error(exc: ValidationError) -> str:
    """A calm, conversational one-liner from a pydantic error — never the raw dump."""
    errs = exc.errors()
    if not errs:
        return "That value doesn't fit this field."
    first = errs[0]
    loc = ".".join(str(p) for p in first.get("loc", ())) or "value"
    msg = first.get("msg", "is invalid")
    return f"That value doesn't fit {loc}: {msg}."
