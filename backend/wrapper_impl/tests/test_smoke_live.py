"""Live smoke test — hits the real Gemini API. Skipped unless GEMINI_API_KEY (or
GOOGLE_API_KEY) is set, so CI stays hermetic and this is run manually.

    GEMINI_API_KEY=... python -m pytest backend/wrapper_impl/tests/test_smoke_live.py -v -s

Proves the E2E integration-step-1 check: a real schema-constrained tool-call
round-trips through the ModelWrapper interface.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from contracts.model_wrapper.interface import Message, ToolDef
from backend.wrapper_impl import GeminiWrapper

_HAS_KEY = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
pytestmark = pytest.mark.skipif(not _HAS_KEY, reason="no Gemini API key in env")


def test_live_text_completion():
    w = GeminiWrapper()
    resp = asyncio.run(w.complete([Message("user", "Reply with exactly the word: pong")]))
    assert resp.text and "pong" in resp.text.lower()


def test_live_tool_call_round_trips():
    w = GeminiWrapper()
    tools = [ToolDef(
        name="book_meeting",
        description="Book a meeting at a given ISO time for a named lead.",
        parameters={
            "type": "object",
            "properties": {
                "lead_name": {"type": "string"},
                "iso_time": {"type": "string"},
            },
            "required": ["lead_name", "iso_time"],
        },
    )]
    msgs = [
        Message("system", "You book meetings by calling the book_meeting tool. Always call the tool."),
        Message("user", "Book a meeting for Dana Lee at 2026-07-03T15:00:00."),
    ]
    resp = asyncio.run(w.complete(msgs, tools=tools))
    assert resp.tool_calls, "expected a tool call"
    call = resp.tool_calls[0]
    assert call.name == "book_meeting"
    assert "lead_name" in call.arguments


def test_live_stream_yields_text():
    w = GeminiWrapper()

    async def run():
        toks = [t async for t in w.stream([Message("user", "Count: one two three")])]
        return "".join(toks)

    out = asyncio.run(run())
    assert out.strip()
