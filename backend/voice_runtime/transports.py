"""Call transports — the provider seam (D9).

`CallTransport` (frozen) moves utterances over some medium. The turn loop in
`engine.py` is transport-agnostic, so text (Phase 1) and voice (Phase 2) differ ONLY
here. Three implementations:

  * `TextTransport`      — the reference transport named by the contract: text I/O,
                           lead turns pushed in from a queue. Lets the exact same
                           `CallEngine` run in a text harness (and the Phase-1 preview
                           surface) with no voice platform at all.
  * `MockVoiceTransport` — a scripted lead for CI: a fixed list of lead utterances,
                           an optional pre-conversation `forced_outcome` (no_answer /
                           voicemail), and a `transfer` hook so warm-transfer is
                           exercised without a real PSTN leg.
  * `RetellTransport`    — the managed-platform adapter (P2-D6/P3-3). Places a real
                           outbound call via the Retell REST API and bridges Retell's
                           "custom LLM" websocket protocol onto this same seam. The
                           Retell SDK (and `websockets`) are imported LAZILY and are
                           mocked in CI; the real leg is a documented smoke test (see
                           DONE.md). Swapping to LiveKit later is another
                           `CallTransport`, no engine change.

`transfer(reason)` is an OPTIONAL extension, deliberately NOT added to the frozen
`CallTransport` Protocol (that would edit a contract). The engine checks for it with
`hasattr`, so a transport that can't warm-transfer simply doesn't advertise one.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator, Optional

from contracts.voice_runtime.interface import CallOutcome, CallTransport, Utterance


class TextTransport:
    """Reference `CallTransport` over text. Lead turns are fed in via `feed()` (or the
    constructor); `send_agent_utterance` appends to `agent_lines` so a harness can read
    the transcript. `receive()` yields queued lead turns until the transport is ended.

    This is the Phase-1 text engine expressed as a transport: it proves the seam is
    exact (same `CallEngine`, no voice platform)."""

    def __init__(self, lead_lines: Optional[list[str]] = None) -> None:
        self._queue: asyncio.Queue[Optional[Utterance]] = asyncio.Queue()
        self.agent_lines: list[str] = []
        self.started = False
        self.ended = False
        self.phone: Optional[str] = None
        for line in lead_lines or []:
            self._queue.put_nowait(Utterance(speaker="lead", text=line))
        # Sentinel closes the stream once the scripted lines are consumed.
        self._queue.put_nowait(None)

    async def start(self, phone: Optional[str]) -> None:
        self.started = True
        self.phone = phone

    def feed(self, text: str) -> None:
        """Push another lead turn (for an interactive harness). Must precede the
        None sentinel to be seen; use before `end()`."""
        self._queue.put_nowait(Utterance(speaker="lead", text=text))

    async def send_agent_utterance(self, text: str) -> None:
        self.agent_lines.append(text)

    async def receive(self) -> AsyncIterator[Utterance]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item

    async def end(self) -> None:
        self.ended = True


class MockVoiceTransport(TextTransport):
    """A scripted voice lead for CI. Adds two voice-specific affordances on top of the
    text reference transport:

      * `forced_outcome` — a pre-conversation platform signal (NO_ANSWER / VOICEMAIL)
        the dialer would surface before any turn; when set, no lead turns are yielded.
      * `transfer(reason)` — records a warm-transfer request so `escalate` can be
        verified end-to-end without a real human leg."""

    def __init__(
        self,
        lead_lines: Optional[list[str]] = None,
        *,
        forced_outcome: Optional[CallOutcome] = None,
    ) -> None:
        # A forced pre-conversation outcome means the call never reaches conversation.
        super().__init__([] if forced_outcome else lead_lines)
        self.forced_outcome = forced_outcome
        self.transferred_to_human = False
        self.transfer_reason: Optional[str] = None

    async def transfer(self, reason: str) -> None:
        self.transferred_to_human = True
        self.transfer_reason = reason


def _import_retell_sdk():
    try:
        import retell  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only in the live smoke
        raise RuntimeError(
            "RetellTransport needs the `retell` package (`pip install retell-sdk`) "
            "installed to place a live call."
        ) from exc
    return retell


def _import_websockets():
    try:
        import websockets  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only in the live smoke
        raise RuntimeError(
            "RetellTransport needs the `websockets` package installed to host the "
            "custom-LLM bridge Retell's platform dials back into."
        ) from exc
    return websockets


def _call_id_from_path(path: str) -> Optional[str]:
    """Retell connects to `{llm_websocket_url}/{call_id}` (one static URL configured
    on the agent; Retell appends the call id per call — docs: integrate-llm/setup-
    websocket-server). Pull the id back out of whatever path we're handed."""
    segment = path.rstrip("/").rsplit("/", 1)[-1] if path else ""
    return segment or None


class _RetellBridgeServer:
    """The ONE process-wide websocket listener every `RetellTransport` shares.

    Retell's platform dials back to a single static `llm_websocket_url` configured
    once on the Retell Agent (out of band) — not a fresh address per call — so this
    must be a singleton that demultiplexes inbound connections by the `call_id` in
    the connection path. `RetellTransport.start()` registers its `call_id` (learned
    from the REST `create_phone_call` response) before Retell can possibly dial back,
    so there's no register/connect race."""

    _instance: Optional["_RetellBridgeServer"] = None
    _instance_lock = asyncio.Lock()

    def __init__(self) -> None:
        self._server = None
        self._pending: dict[str, "RetellTransport"] = {}

    @classmethod
    async def shared(cls) -> "_RetellBridgeServer":
        async with cls._instance_lock:
            if cls._instance is None:
                bridge = cls()
                await bridge._listen()
                cls._instance = bridge
            return cls._instance

    async def _listen(self) -> None:
        websockets = _import_websockets()
        host = os.getenv("RETELL_WS_HOST", "0.0.0.0")
        port = int(os.getenv("RETELL_WS_PORT", "8765"))
        self._server = await websockets.serve(self._handle, host, port)

    def register(self, call_id: str, transport: "RetellTransport") -> None:
        self._pending[call_id] = transport

    def unregister(self, call_id: str) -> None:
        self._pending.pop(call_id, None)

    async def _handle(self, websocket) -> None:
        request = getattr(websocket, "request", None)
        path = getattr(request, "path", None) or getattr(websocket, "path", "")
        call_id = _call_id_from_path(path)
        transport = self._pending.pop(call_id, None) if call_id else None
        if transport is None:  # pragma: no cover - live leg only
            await websocket.close(code=4404, reason="unrecognized call_id")
            return
        await transport._bridge_connected(websocket)


class RetellTransport:
    """Managed-platform adapter (Retell v1, P2-D6/P3-3). The SDK import is lazy and
    lives ONLY here (D8: provider SDKs never leak past their adapter). Unconfigured,
    it raises with a clear message rather than importing at module load, so CI —
    which uses the mock transports — never needs the SDK installed.

    `start()` places the call over Retell's REST API
    (`AsyncRetell.call.create_phone_call`), then waits for Retell's platform to dial
    back into the shared `_RetellBridgeServer` over its "custom LLM" websocket
    protocol (docs: integrate-llm/overview). From there the wire protocol maps
    directly onto `CallTransport`:

      * a `response_required` / `reminder_required` frame carrying a fresh lead
        utterance -> one `Utterance` yielded from `receive()`
      * `send_agent_utterance(text)` -> a `response` frame answering the most
        recent `response_id`
      * `transfer(reason)` -> a `response` frame with `transfer_number` set (warm
        transfer, P2-D6)
      * `end()` -> a `response` frame with `end_call: true`, then the bridge
        registration is torn down

    Known simplification (documented, not a protocol violation): a `reminder_required`
    frame with no new lead turn (the lead went quiet) is acknowledged for `response_id`
    bookkeeping but does not synthesize a lead `Utterance` — the engine only speaks
    again once the lead actually replies. Real no-answer/voicemail detection (a call
    that never connects) is not wired here; today it surfaces as an empty transcript,
    classified heuristically like any short call. Real wiring + a live smoke test are
    documented in DONE.md."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        agent_number: Optional[str] = None,
        transfer_number: Optional[str] = None,
        connect_timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._agent_number = agent_number
        self._transfer_number = transfer_number or os.getenv("RETELL_TRANSFER_NUMBER")
        self._connect_timeout = connect_timeout

        self._client = None  # set in start(), lazily
        self._connection = None  # the Retell websocket connection, once dialed back
        self._connected = asyncio.Event()
        self._response_ready = asyncio.Event()
        self._response_id: int = 0
        self._call_id: Optional[str] = None
        self._incoming: "asyncio.Queue[Optional[Utterance]]" = asyncio.Queue()
        self._closed = False

    async def start(self, phone: Optional[str]) -> None:
        if not self._api_key:
            raise RuntimeError(
                "RetellTransport is a documented seam, not wired for CI. Provide an "
                "api_key and install the Retell SDK to place a live call, or use "
                "MockVoiceTransport in tests (see DONE.md)."
            )
        if not self._agent_number:
            raise RuntimeError(
                "RetellTransport needs agent_number (RETELL_FROM_NUMBER) — the "
                "Retell-owned caller id to dial out from."
            )

        # Lazy imports keep the provider SDK + ws server out of every non-live path.
        retell = _import_retell_sdk()
        bridge = await _RetellBridgeServer.shared()

        self._client = retell.AsyncRetell(api_key=self._api_key)
        call = await self._client.call.create_phone_call(
            from_number=self._agent_number, to_number=phone
        )
        self._call_id = call.call_id
        bridge.register(self._call_id, self)
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=self._connect_timeout)
        except asyncio.TimeoutError as exc:
            bridge.unregister(self._call_id)
            raise RuntimeError(
                f"Retell never dialed back the llm-websocket for call {self._call_id} "
                f"within {self._connect_timeout}s."
            ) from exc

    async def _bridge_connected(self, websocket) -> None:
        """Called by `_RetellBridgeServer` once Retell's platform dials back for
        THIS call. Owns the connection for the rest of the call's lifetime."""
        self._connection = websocket
        self._connected.set()
        try:
            async for raw in websocket:
                await self._on_message(json.loads(raw))
        finally:
            if not self._closed:
                self._incoming.put_nowait(None)  # Retell hung up the leg

    async def _on_message(self, msg: dict) -> None:
        kind = msg.get("interaction_type")
        if kind == "ping_pong":
            await self._connection.send(
                json.dumps({"response_type": "ping_pong", "timestamp": msg.get("timestamp", 0)})
            )
            return
        if kind not in ("response_required", "reminder_required"):
            return  # `call_details` / `update_only` are informational only

        self._response_id = msg.get("response_id", self._response_id)
        self._response_ready.set()
        transcript = msg.get("transcript") or []
        last = transcript[-1] if transcript else None
        if last and last.get("role") == "user" and last.get("content"):
            await self._incoming.put(Utterance(speaker="lead", text=last["content"]))
        # See the class docstring's "known simplification" for reminder_required /
        # the opening (empty-transcript) response_required: no lead Utterance, but
        # `send_agent_utterance` still has a fresh `response_id` to answer against.

    async def send_agent_utterance(self, text: str) -> None:
        await asyncio.wait_for(self._response_ready.wait(), timeout=self._connect_timeout)
        self._response_ready.clear()
        await self._connection.send(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": self._response_id,
                    "content": text,
                    "content_complete": True,
                }
            )
        )

    async def receive(self) -> AsyncIterator[Utterance]:
        while True:
            item = await self._incoming.get()
            if item is None:
                return
            yield item

    async def transfer(self, reason: str) -> None:
        if self._connection is None:  # pragma: no cover - live leg only
            return
        if not self._transfer_number:
            raise RuntimeError(
                "RetellTransport.transfer needs transfer_number (RETELL_TRANSFER_NUMBER)."
            )
        await self._connection.send(
            json.dumps(
                {
                    "response_type": "response",
                    "response_id": self._response_id,
                    "content": "",
                    "content_complete": True,
                    "transfer_number": self._transfer_number,
                }
            )
        )

    async def end(self) -> None:
        self._closed = True
        if self._connection is not None:
            try:
                await self._connection.send(
                    json.dumps(
                        {
                            "response_type": "response",
                            "response_id": self._response_id,
                            "content": "",
                            "content_complete": True,
                            "end_call": True,
                        }
                    )
                )
            except Exception:  # pragma: no cover - leg may already be closing
                pass
        self._incoming.put_nowait(None)
        if self._call_id and _RetellBridgeServer._instance is not None:
            _RetellBridgeServer._instance.unregister(self._call_id)
