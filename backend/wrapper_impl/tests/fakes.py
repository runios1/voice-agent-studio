"""In-memory fakes standing in for the google-genai async client.

These let us exercise GeminiWrapper's request-shaping, response-collapsing, retry
and streaming logic with zero network. They record what config the wrapper built so
tests can assert the contract->SDK mapping.
"""

from __future__ import annotations

from typing import Any, Optional

from google.genai import types


class FakeModels:
    def __init__(self, owner: "FakeAsyncClient") -> None:
        self._owner = owner

    async def generate_content(self, *, model, contents, config):
        self._owner.record(model=model, contents=contents, config=config)
        return self._owner.next_response()

    async def generate_content_stream(self, *, model, contents, config):
        self._owner.record(model=model, contents=contents, config=config)
        return _aiter(self._owner.next_stream())


class FakeAio:
    def __init__(self, owner: "FakeAsyncClient") -> None:
        self.models = FakeModels(owner)


class FakeAsyncClient:
    """Drop-in for genai.Client. Feed it responses/streams and/or an error script."""

    def __init__(
        self,
        responses: Optional[list[types.GenerateContentResponse]] = None,
        streams: Optional[list[list[types.GenerateContentResponse]]] = None,
        errors: Optional[list[Optional[Exception]]] = None,
    ) -> None:
        self._responses = list(responses or [])
        self._streams = list(streams or [])
        # errors[i]: if not None, raised on call i (before consuming a response).
        self._errors = list(errors or [])
        self.calls: list[dict[str, Any]] = []
        self.aio = FakeAio(self)

    # -- recording / scripting --------------------------------------------------
    def record(self, **kw: Any) -> None:
        idx = len(self.calls)
        self.calls.append(kw)
        if idx < len(self._errors) and self._errors[idx] is not None:
            raise self._errors[idx]

    def next_response(self) -> types.GenerateContentResponse:
        return self._responses.pop(0)

    def next_stream(self) -> list[types.GenerateContentResponse]:
        return self._streams.pop(0)

    @property
    def last_config(self) -> types.GenerateContentConfig:
        return self.calls[-1]["config"]


async def _aiter(items):
    for it in items:
        yield it


# -- response builders -----------------------------------------------------------

def text_response(text: str) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text=text)])
            )
        ]
    )


def tool_call_response(name: str, args: dict) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
                )
            )
        ]
    )
