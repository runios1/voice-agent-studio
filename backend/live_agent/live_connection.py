"""The Live wire, normalized to a small internal seam.

`GeminiLiveAgentSession` (session.py) is written against `LiveConnection` below, NOT
against `google.genai` directly — so tests drive it with a `FakeLiveConnection`
(tests/fakes.py) and CI never imports the SDK (D8: provider SDKs stay lazily
imported behind their adapter, same posture as `wrapper_impl` / `GeminiLiveSpeechBridge`).
`GeminiLiveConnection` + `default_live_connector` are the real adapter, exercised only
by the documented live smoke test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, AsyncContextManager, AsyncIterator, Callable, Optional, Protocol

from contracts.live_agent.interface import LiveAgentSpec


@dataclass
class LiveFunctionCall:
    """One function Live requested. `id` round-trips back on `send_tool_response`."""

    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LiveEvent:
    """One normalized message off the Live wire. A real message usually populates
    exactly one of these; all fields are optional/defaulted so callers only check
    what they care about."""

    audio: Optional[bytes] = None
    output_transcript_delta: Optional[str] = None
    input_transcript_delta: Optional[str] = None
    turn_complete: bool = False
    interrupted: bool = False  # Live's own barge-in signal (caller started talking)
    function_calls: list[LiveFunctionCall] = field(default_factory=list)


class LiveConnection(Protocol):
    """One connected Live session, normalized to exactly what the session runtime
    needs: push mic audio in, get `LiveEvent`s out, answer function calls, and steer
    the conversation back on guardrail after a moderation cut."""

    async def send_audio(self, pcm: bytes) -> None: ...
    async def send_tool_response(self, responses: list[dict[str, Any]]) -> None: ...
    async def send_steer(self, instruction: str) -> None: ...
    async def send_kickoff(self, prompt: str) -> None: ...
    def receive(self) -> AsyncIterator[LiveEvent]: ...


# config -> an async context manager yielding a connected `LiveConnection`. Kept as a
# plain callable (not a class) so tests inject a trivial async-context-manager fake.
LiveConnector = Callable[[LiveAgentSpec], "AsyncContextManager[LiveConnection]"]


class GeminiLiveConnection:
    """Adapts one `google.genai` Live session to `LiveConnection`. Constructed only by
    `_LiveConnectionCM.__aenter__`; never instantiated in tests."""

    def __init__(self, session: Any, types_mod: Any) -> None:
        self._session = session
        self._types = types_mod

    async def send_audio(self, pcm: bytes) -> None:  # pragma: no cover - live smoke
        await self._session.send_realtime_input(
            audio=self._types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
        )

    async def send_tool_response(
        self, responses: list[dict[str, Any]]
    ) -> None:  # pragma: no cover - live smoke
        types = self._types
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(id=r["id"], name=r["name"], response=r["response"])
                for r in responses
            ]
        )

    async def send_steer(self, instruction: str) -> None:  # pragma: no cover - live smoke
        types = self._types
        await self._session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=instruction)]),
            turn_complete=True,
        )

    async def send_kickoff(self, prompt: str) -> None:  # pragma: no cover - live smoke
        """Nudge Live to take the FIRST turn (it otherwise waits for the caller), so the
        agent opens the call — with its LOCKED disclosure — the instant we connect."""
        types = self._types
        await self._session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=prompt)]),
            turn_complete=True,
        )

    def receive(self) -> AsyncIterator[LiveEvent]:
        return self._read_loop()

    async def _read_loop(self) -> AsyncIterator[LiveEvent]:  # pragma: no cover - live smoke
        # `session.receive()` yields exactly ONE model turn then stops (it breaks on
        # turn_complete). Loop it so the conversation continues past the agent's opening
        # turn — without this the call ends after turn one and the mic pump is torn down,
        # so nothing ever hears the caller. The loop ends when the Live socket closes
        # (receive() yields nothing / raises), which winds the call down normally.
        while True:
            produced = False
            try:
                async for msg in self._session.receive():
                    produced = True
                    sc = getattr(msg, "server_content", None)
                    tc = getattr(msg, "tool_call", None)
                    if sc is not None:
                        audio = None
                        model_turn = getattr(sc, "model_turn", None)
                        if model_turn is not None:
                            for part in model_turn.parts or []:
                                inline = getattr(part, "inline_data", None)
                                if inline is not None and inline.data:
                                    audio = inline.data
                        out_tr = getattr(sc, "output_transcription", None)
                        in_tr = getattr(sc, "input_transcription", None)
                        yield LiveEvent(
                            audio=audio,
                            output_transcript_delta=getattr(out_tr, "text", None) if out_tr else None,
                            input_transcript_delta=getattr(in_tr, "text", None) if in_tr else None,
                            turn_complete=bool(getattr(sc, "turn_complete", False)),
                            interrupted=bool(getattr(sc, "interrupted", False)),
                        )
                    if tc is not None:
                        calls = [
                            LiveFunctionCall(id=fc.id, name=fc.name, args=dict(fc.args or {}))
                            for fc in (tc.function_calls or [])
                        ]
                        if calls:
                            yield LiveEvent(function_calls=calls)
            except Exception:
                return  # Live socket closed/errored — end the stream; the call winds down
            if not produced:
                return  # receive() returned nothing -> session closed


# Gemini Live's FunctionDeclaration parameters are an OpenAPI-3 subset, NOT full JSON
# Schema: keys like `additionalProperties` are rejected at connect (API 1007 "Unknown
# name additional_properties"). Strip what it doesn't accept — recursively, since a
# nested object property can carry it too — when translating a declaration to the wire.
_LIVE_SCHEMA_UNSUPPORTED = {"additionalProperties"}


def _live_schema(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: _live_schema(v) for k, v in node.items() if k not in _LIVE_SCHEMA_UNSUPPORTED
        }
    if isinstance(node, list):
        return [_live_schema(v) for v in node]
    return node


class _LiveConnectionCM:
    """Async context manager: opens the Live session (system instruction + tool
    declarations + in/out transcription from the spec), yields the adapter, tears
    down the underlying SDK session on exit."""

    def __init__(self, spec: LiveAgentSpec) -> None:
        self._spec = spec
        self._cm = None

    async def __aenter__(self) -> LiveConnection:  # pragma: no cover - live smoke
        import google.genai as genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key)
        model = self._spec.model or os.getenv(
            "GEMINI_MODEL_VOICE_LIVE", "gemini-3.1-flash-live-preview"
        )
        tools = None
        if self._spec.tool_declarations:
            tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=d["name"],
                            description=d.get("description"),
                            parameters=_live_schema(d.get("parameters")),
                        )
                        for d in self._spec.tool_declarations
                    ]
                )
            ]
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self._spec.system_instruction,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._spec.voice_name)
                )
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            tools=tools,
        )
        self._cm = client.aio.live.connect(model=model, config=config)
        session = await self._cm.__aenter__()
        return GeminiLiveConnection(session, types)

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - live smoke
        if self._cm is not None:
            await self._cm.__aexit__(exc_type, exc, tb)


def default_live_connector(spec: LiveAgentSpec) -> AsyncContextManager[LiveConnection]:
    """The production `LiveConnector`: lazily imports `google.genai` (D8) so a
    key-less/SDK-less checkout never touches it — only the documented live smoke test
    exercises this path."""
    return _LiveConnectionCM(spec)
