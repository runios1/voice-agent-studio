"""Unit tests for the small pure helpers in live_connection (the SDK path itself is
live-smoke-only)."""

from __future__ import annotations

from backend.live_agent.live_connection import _live_schema


def test_live_schema_strips_additional_properties_recursively():
    """Gemini Live rejects JSON-Schema's `additionalProperties` (API 1007). It must be
    removed at every level before a declaration goes on the wire."""
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "outcome": {"type": "string", "enum": ["qualified", "not_qualified"]},
            "nested": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"x": {"type": "string"}},
            },
        },
        "required": ["outcome"],
    }
    out = _live_schema(schema)

    assert "additionalProperties" not in out
    assert "additionalProperties" not in out["properties"]["nested"]
    # everything the API DOES accept is preserved untouched
    assert out["properties"]["outcome"]["enum"] == ["qualified", "not_qualified"]
    assert out["properties"]["nested"]["properties"]["x"] == {"type": "string"}
    assert out["required"] == ["outcome"]


def test_live_schema_passes_through_none_scalars_and_lists():
    assert _live_schema(None) is None
    assert _live_schema("qualified") == "qualified"
    assert _live_schema([{"additionalProperties": True, "a": 1}]) == [{"a": 1}]


def test_compiled_declarations_carry_no_unsupported_keys_after_sanitizing():
    """End-to-end: the compiler's real declarations (end_call, and calendar when on)
    are Live-clean once sanitized."""
    from backend.live_agent.compiler import LiveAgentCompilerImpl
    from backend.runtime_loop.fixtures import sample_ready_config

    config = sample_ready_config()
    config.automation.calendar.enabled = True
    spec = LiveAgentCompilerImpl().compile(config)

    def _has_key(node, key):
        if isinstance(node, dict):
            return key in node or any(_has_key(v, key) for v in node.values())
        if isinstance(node, list):
            return any(_has_key(v, key) for v in node)
        return False

    for decl in spec.tool_declarations:
        cleaned = _live_schema(decl.get("parameters"))
        assert not _has_key(cleaned, "additionalProperties")
