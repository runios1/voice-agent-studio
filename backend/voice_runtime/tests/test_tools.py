"""In-call tool layer — enabled-function rule + least-privilege ToolDefs."""

from __future__ import annotations

from backend.voice_runtime.fixtures import config_with_calendar
from backend.voice_runtime.mocks import MockToolRegistry
from backend.voice_runtime.tools import build_tool_defs, enabled_in_call_tools

from backend.runtime_loop.fixtures import sample_ready_config


def test_disabled_automation_exposes_no_tool():
    # calendar disabled in the base fixture -> nothing exposed even though the registry
    # catalogs book_meeting.
    tools = enabled_in_call_tools(sample_ready_config(), MockToolRegistry())
    assert tools == []


def test_enabled_calendar_exposes_only_in_call_book_meeting():
    tools = enabled_in_call_tools(config_with_calendar(), MockToolRegistry())
    assert [t.name for t in tools] == ["calendar"]


def test_tool_defs_are_least_privilege():
    defs = build_tool_defs(config_with_calendar(), MockToolRegistry())
    assert len(defs) == 1
    params = defs[0].parameters
    # The model may pick a time and nothing else — no calendar id, attendee, or length.
    assert set(params["properties"]) == {"start_iso"}
    assert params["additionalProperties"] is False


def test_post_call_tool_never_in_call_even_if_enabled():
    config = config_with_calendar()
    config.automation.email.enabled = True
    names = [t.name for t in enabled_in_call_tools(config, MockToolRegistry())]
    assert "email" not in names
