"""`BrowserVoiceTransport` — the frozen `CallTransport` for the browser preview (P3-4).

`CallEngine.run_call` (backend/voice_runtime/engine.py) only ever talks to a
`CallTransport`: `start` / `send_agent_utterance` / `receive` / `end`. This is that
transport for one browser preview call, bridging a WS connection's PCM frames to/from
the engine's text turns via an injected `SpeechBridge` (see speech_bridge.py).

A websocket has exactly one reader, and that reader lives in `router.py` (it also has
to watch for the `stop` control message). So inbound audio does NOT arrive through this
class reading the socket — it's PUSHED in via `push_audio`/`push_stop` from the
router's receive loop, buffered/transcribed here, then handed to the engine through
`receive()`, the same shape as `TextTransport`'s internal queue."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Awaitable, Callable, Optional

from contracts.voice_runtime.interface import Utterance

from backend.voice_preview.speech_bridge import SpeechBridge

# Outbound senders, injected so this module never imports Starlette directly and a
# test can assert on plain in-memory lists.
SendJSON = Callable[[dict], Awaitable[None]]
SendAudio = Callable[[bytes], Awaitable[None]]


class BrowserVoiceTransport:
    """One preview call's `CallTransport`. `phone` is always None (no PSTN leg) —
    the frozen `CallTransport.start(phone)` signature is unchanged, it's just unused
    here, matching `TextTransport`'s reference treatment of `phone`."""

    def __init__(self, bridge: SpeechBridge, send_json: SendJSON, send_audio: SendAudio) -> None:
        self._bridge = bridge
        self._send_json = send_json
        self._send_audio = send_audio
        self._queue: asyncio.Queue[Optional[Utterance]] = asyncio.Queue()
        self._stopped = False

    async def start(self, phone: Optional[str]) -> None:
        await self._bridge.start()

    async def send_agent_utterance(self, text: str) -> None:
        # Transcript first so the UI shows text promptly even if audio trails behind.
        await self._send_json({"type": "transcript", "role": "agent", "text": text})
        async for chunk in self._bridge.synthesize(text):
            await self._send_audio(chunk)

    async def receive(self) -> AsyncIterator[Utterance]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def end(self) -> None:
        await self._bridge.close()

    # ---- fed by the router's single WS-receive loop; the engine never calls these --- #
    async def push_audio(self, chunk: bytes) -> None:
        """One inbound binary frame (lead mic audio). Feeds the bridge; once a turn
        is finalized, surfaces it both to the UI (transcript) and to the engine
        (queued `Utterance`)."""
        if self._stopped:
            return
        text = await self._bridge.feed_audio(chunk)
        if text:
            await self._send_json({"type": "transcript", "role": "lead", "text": text})
            self._queue.put_nowait(Utterance(speaker="lead", text=text))

    def push_stop(self) -> None:
        """The client hung up / closed the mic, or the socket dropped. Idempotent:
        unblocks `receive()` so the engine's `_converse` loop ends and `run_call`
        proceeds to `transport.end()`."""
        if self._stopped:
            return
        self._stopped = True
        self._queue.put_nowait(None)
