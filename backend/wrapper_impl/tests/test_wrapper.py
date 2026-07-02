"""GeminiWrapper behavior tests, driven against a fake async client (no network).

Async methods are exercised via asyncio.run so no pytest-asyncio config is needed.
"""

from __future__ import annotations

import asyncio

import pytest
from google.genai import errors as genai_errors

from contracts.model_wrapper.interface import Message, ModelResponse, ToolDef
from backend.wrapper_impl import GeminiWrapper, WrapperUsageError
from backend.wrapper_impl.config import ConfigError, GeminiConfig
from .fakes import FakeAsyncClient, text_response, tool_call_response


def _wrapper(client, **cfg_over):
    cfg = GeminiConfig(api_key="test-key", **cfg_over)
    return GeminiWrapper(config=cfg, client=client)


async def _collect(agen):
    return [tok async for tok in agen]


# -- complete() -----------------------------------------------------------------

def test_complete_returns_text_response_shape():
    client = FakeAsyncClient(responses=[text_response("hi there")])
    w = _wrapper(client)
    resp = asyncio.run(w.complete([Message("user", "hello")]))
    assert isinstance(resp, ModelResponse)
    assert resp.text == "hi there"
    assert resp.tool_calls == []


def test_complete_round_trips_a_schema_constrained_tool_call():
    client = FakeAsyncClient(responses=[tool_call_response("set_field", {"path": "conversation.tone", "value": "warm"})])
    w = _wrapper(client)
    tools = [ToolDef("set_field", "set a config field", {
        "type": "object",
        "properties": {"path": {"type": "string"}, "value": {}},
        "required": ["path"],
    })]
    resp = asyncio.run(w.complete([Message("user", "make it warm")], tools=tools))
    assert resp.tool_calls[0].name == "set_field"
    assert resp.tool_calls[0].arguments == {"path": "conversation.tone", "value": "warm"}
    # the tool schema reached the SDK config verbatim
    decl = client.last_config.tools[0].function_declarations[0]
    assert decl.parameters_json_schema["required"] == ["path"]


def test_complete_maps_tier_to_model_id():
    client = FakeAsyncClient(responses=[text_response("x"), text_response("y")])
    w = _wrapper(client, models={"frontier": "model-fr", "fast": "model-fa", "voice": "model-vo"})
    asyncio.run(w.complete([Message("user", "a")], model_tier="fast"))
    assert client.calls[-1]["model"] == "model-fa"
    asyncio.run(w.complete([Message("user", "b")], model_tier="frontier"))
    assert client.calls[-1]["model"] == "model-fr"


def test_unknown_tier_falls_back_to_frontier():
    client = FakeAsyncClient(responses=[text_response("x")])
    w = _wrapper(client, models={"frontier": "model-fr", "fast": "model-fa", "voice": "model-vo"})
    asyncio.run(w.complete([Message("user", "a")], model_tier="bogus"))
    assert client.calls[-1]["model"] == "model-fr"


def test_complete_rejects_tools_and_schema_together():
    client = FakeAsyncClient(responses=[text_response("x")])
    w = _wrapper(client)
    with pytest.raises(WrapperUsageError):
        asyncio.run(w.complete(
            [Message("user", "a")],
            tools=[ToolDef("f", "d", {"type": "object"})],
            response_schema={"type": "object"},
        ))


# -- stream() -------------------------------------------------------------------

def test_stream_yields_text_deltas_only():
    stream = [text_response("Hel"), text_response("lo"), text_response("!")]
    client = FakeAsyncClient(streams=[stream])
    w = _wrapper(client)
    toks = asyncio.run(_collect(w.stream([Message("user", "hi")])))
    assert toks == ["Hel", "lo", "!"]


def test_stream_drops_function_call_chunks():
    stream = [text_response("Book"), tool_call_response("hold_slot", {"t": "3pm"}), text_response("ing")]
    client = FakeAsyncClient(streams=[stream])
    w = _wrapper(client)
    toks = asyncio.run(_collect(w.stream([Message("user", "hi")], tools=[ToolDef("hold_slot", "d", {"type": "object"})])))
    assert toks == ["Book", "ing"]  # no function-call text leaked into the feed


# -- retry / timeout ------------------------------------------------------------

def test_retry_on_transient_then_succeeds():
    client = FakeAsyncClient(
        responses=[text_response("ok")],
        errors=[genai_errors.ServerError(503, {"error": {"message": "unavailable"}})],
    )
    w = _wrapper(client, max_retries=2)
    resp = asyncio.run(w.complete([Message("user", "a")]))
    assert resp.text == "ok"
    assert len(client.calls) == 2  # one failed, one retried


def test_retry_on_429():
    client = FakeAsyncClient(
        responses=[text_response("ok")],
        errors=[genai_errors.ClientError(429, {"error": {"message": "rate"}})],
    )
    w = _wrapper(client, max_retries=2)
    resp = asyncio.run(w.complete([Message("user", "a")]))
    assert resp.text == "ok"


def test_no_retry_on_client_4xx():
    client = FakeAsyncClient(
        responses=[text_response("never")],
        errors=[genai_errors.ClientError(400, {"error": {"message": "bad request"}})],
    )
    w = _wrapper(client, max_retries=3)
    with pytest.raises(genai_errors.ClientError):
        asyncio.run(w.complete([Message("user", "a")]))
    assert len(client.calls) == 1  # failed once, not retried


def test_retries_are_bounded():
    # every attempt fails transiently; wrapper gives up after max_retries+1 tries
    client = FakeAsyncClient(
        responses=[text_response("never")],
        errors=[genai_errors.ServerError(500, {"error": {"m": "x"}})] * 5,
    )
    w = _wrapper(client, max_retries=2)
    with pytest.raises(genai_errors.ServerError):
        asyncio.run(w.complete([Message("user", "a")]))
    assert len(client.calls) == 3  # 1 initial + 2 retries


# -- config ---------------------------------------------------------------------

def test_from_env_requires_a_key(monkeypatch):
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_USE_VERTEX", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ConfigError):
        GeminiConfig.from_env()


def test_from_env_reads_model_overrides(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("GEMINI_MODEL_FRONTIER", "custom-pro")
    cfg = GeminiConfig.from_env()
    assert cfg.model_for("frontier") == "custom-pro"
    assert cfg.model_for("fast") == "gemini-3.5-flash"  # default preserved
