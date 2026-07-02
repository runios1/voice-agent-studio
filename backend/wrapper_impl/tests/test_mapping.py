"""Pure-mapping unit tests — no client, no network."""

from __future__ import annotations

import pytest

from contracts.model_wrapper.interface import Message, ToolDef
from backend.wrapper_impl import _mapping
from backend.wrapper_impl._mapping import WrapperUsageError
from .fakes import text_response, tool_call_response


def test_system_messages_are_hoisted_and_concatenated():
    sys_instr, contents = _mapping.split_messages(
        [
            Message("system", "Rule A"),
            Message("system", "Rule B"),
            Message("user", "hello"),
        ]
    )
    assert sys_instr == "Rule A\n\nRule B"
    assert len(contents) == 1
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "hello"


def test_assistant_maps_to_model_role():
    _, contents = _mapping.split_messages(
        [Message("user", "hi"), Message("assistant", "hey")]
    )
    assert [c.role for c in contents] == ["user", "model"]


def test_tool_message_is_lossy_user_turn_with_prefix():
    _, contents = _mapping.split_messages([Message("tool", "calendar: free at 3pm")])
    assert contents[0].role == "user"
    assert contents[0].parts[0].text == "[tool result] calendar: free at 3pm"


def test_no_system_message_yields_none_instruction():
    sys_instr, _ = _mapping.split_messages([Message("user", "hi")])
    assert sys_instr is None


def test_tools_pass_json_schema_through_verbatim():
    schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
    tools = _mapping.to_tools([ToolDef("set_field", "set a field", schema)])
    decl = tools[0].function_declarations[0]
    assert decl.name == "set_field"
    assert decl.parameters_json_schema == schema


def test_tools_none_returns_none():
    assert _mapping.to_tools(None) is None
    assert _mapping.to_tools([]) is None


def test_build_config_rejects_tools_and_response_schema_together():
    with pytest.raises(WrapperUsageError):
        _mapping.build_config(
            system_instruction=None,
            tools=[ToolDef("f", "d", {"type": "object"})],
            response_schema={"type": "object"},
            timeout_s=60.0,
        )


def test_build_config_tools_disables_auto_function_calling():
    cfg = _mapping.build_config(
        system_instruction="sys",
        tools=[ToolDef("f", "d", {"type": "object"})],
        response_schema=None,
        timeout_s=30.0,
    )
    assert cfg.tools is not None
    assert cfg.automatic_function_calling.disable is True
    assert cfg.http_options.timeout == 30000  # seconds -> ms
    assert cfg.response_json_schema is None


def test_build_config_response_schema_sets_json_mode():
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    cfg = _mapping.build_config(
        system_instruction=None, tools=None, response_schema=schema, timeout_s=60.0
    )
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == schema
    assert cfg.tools is None


def test_to_model_response_collapses_text():
    resp = _mapping.to_model_response(text_response("hello world"))
    assert resp.text == "hello world"
    assert resp.tool_calls == []


def test_to_model_response_collapses_tool_call():
    resp = _mapping.to_model_response(tool_call_response("set_field", {"path": "a.b", "value": 1}))
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "set_field"
    assert resp.tool_calls[0].arguments == {"path": "a.b", "value": 1}


def test_text_delta_drops_non_text_chunk():
    # a chunk carrying only a function_call has no text delta
    chunk = tool_call_response("f", {"x": 1})
    assert _mapping.text_delta(chunk) is None
    assert _mapping.text_delta(text_response("tok")) == "tok"
