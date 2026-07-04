"""Twilio Media Streams <-> Gemini Live bridge (the phone leg of the Live agent).

The preview runs `GeminiLiveAgentSession` over a browser `AudioTransport` (PCM over a
WS). This is the SAME session over a *phone* `AudioTransport`: Twilio places the real
outbound call, forks the call's audio to our websocket as 8 kHz μ-law, and plays back
whatever μ-law we send — so the caller talks to the identical Live agent, just over the
PSTN. Only the medium differs; the session, compiler, tools, moderation and events are
all unchanged.

Lifecycle (mirrors RetellTransport's place-then-dial-back, but over the app's own WS
route so there's one public endpoint):

  1. `PhoneAudioTransport.start()` registers the call under a one-time token, POSTs the
     outbound call to Twilio's REST API with TwiML that `<Connect><Stream>`s to
     `wss://{PUBLIC_WSS_BASE}/twilio/media/{token}`, and waits for Twilio to connect
     that stream and send its `start` frame (which carries the streamSid we answer on).
     If nobody answers within the timeout, start() raises `PhoneNotAnswered`.
  2. Twilio connects -> the media route (`create_twilio_media_router`) hands the socket
     to the waiting transport, which then reads inbound frames for the call's lifetime.
  3. The session drives `recv_audio()` (caller -> agent, μ-law 8k -> PCM 16k) and
     `send_audio()` (agent -> caller, PCM 24k -> μ-law 8k); `cut_playback()` sends
     Twilio a `clear` (barge-in). `send_event()` is a no-op (there is no phone UI).

Audio conversion is `telephony_codec` (validated against the live model).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
from typing import AsyncIterator, Awaitable, Callable, Optional, Protocol

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.live_agent.telephony_codec import live_to_phone, phone_to_live


class PhoneNotAnswered(Exception):
    """Twilio never connected the media stream before the timeout — no answer / busy /
    the callee hung up before picking up. The dialer maps this to a NO_ANSWER outcome."""


# One-time token -> the transport awaiting Twilio's dial-back. A call registers before
# it can possibly connect, so there is no register/connect race (same posture as the
# Retell bridge). Process-local: fine for a single app process; a multi-process deploy
# would key this off a shared store.
_PENDING: dict[str, "PhoneAudioTransport"] = {}


# --- outbound call placement (Twilio REST over httpx — no SDK dependency) ----- #
class CallPlacer(Protocol):
    """Places/hangs up the real outbound leg. Injected so tests never hit Twilio."""

    async def place(self, *, to: str, from_: str, twiml: str) -> str: ...  # -> call sid
    async def hangup(self, call_sid: str) -> None: ...


class TwilioRestPlacer:
    """The real placer: Twilio's 2010 REST API, HTTP Basic auth, httpx (already a dep)."""

    _BASE = "https://api.twilio.com/2010-04-01/Accounts"

    def __init__(self, account_sid: str, auth_token: str) -> None:
        self._sid = account_sid
        self._auth = (account_sid, auth_token)

    async def place(self, *, to: str, from_: str, twiml: str) -> str:  # pragma: no cover - live leg
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._BASE}/{self._sid}/Calls.json",
                auth=self._auth,
                data={"To": to, "From": from_, "Twiml": twiml},
            )
            resp.raise_for_status()
            return resp.json()["sid"]

    async def hangup(self, call_sid: str) -> None:  # pragma: no cover - live leg
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                await client.post(
                    f"{self._BASE}/{self._sid}/Calls/{call_sid}.json",
                    auth=self._auth,
                    data={"Status": "completed"},
                )
            except Exception:
                pass  # best effort; the leg may already be down


# --- verified caller IDs (demo/trial support) --------------------------------- #
# A Twilio *trial* account may only call numbers that are registered as verified caller
# IDs. Verification is a proof-of-ownership flow by design: Twilio places a call to the
# number and the person must answer and key in a spoken 6-digit code — there is NO API
# to silently mark an arbitrary number verified. So this only helps when the demo
# "leads" are phones you can actually answer. A paid (non-trial) account needs none of
# this and should use the no-op verifier.
class CallerIdVerifier(Protocol):
    """Kicks off (and waits on) Twilio's verified-caller-ID flow for a destination number.
    Injected so tests/dev never hit Twilio."""

    async def verify(self, phone: str, *, friendly_name: Optional[str] = None) -> Optional[str]:
        """Start verification. Returns the 6-digit code Twilio speaks on its verification
        call, or None if it couldn't be started."""
        ...

    async def wait_until_verified(self, phone: str, *, timeout: Optional[float] = None) -> bool:
        """Block until `phone` is a verified caller ID (the callee answered + entered the
        code), or the timeout elapses. Returns True once verified, False on timeout — the
        dialer gates each call on this so a trial account never places a call that Twilio
        would reject."""
        ...


class NullCallerIdVerifier:
    """No-op default: paid accounts don't need verification, and dev/tests shouldn't call
    Twilio. `wait_until_verified` returns True immediately so it never gates dialing."""

    async def verify(self, phone: str, *, friendly_name: Optional[str] = None) -> Optional[str]:
        return None

    async def wait_until_verified(self, phone: str, *, timeout: Optional[float] = None) -> bool:
        return True


class TwilioCallerIdVerifier:
    """Real verifier: `POST /OutgoingCallerIds.json` makes Twilio call `phone` and speak a
    6-digit code the callee must enter to prove ownership. On success the number becomes a
    verified caller ID the (trial) account may dial. `wait_until_verified` polls the
    account's verified list until the number shows up. Same creds as the placer."""

    _BASE = "https://api.twilio.com/2010-04-01/Accounts"

    def __init__(
        self, account_sid: str, auth_token: str, *, wait_timeout: float = 180.0, poll_interval: float = 3.0
    ) -> None:
        self._sid = account_sid
        self._auth = (account_sid, auth_token)
        self._wait_timeout = wait_timeout
        self._poll_interval = poll_interval

    async def verify(  # pragma: no cover - live leg
        self, phone: str, *, friendly_name: Optional[str] = None
    ) -> Optional[str]:
        import httpx

        data = {"PhoneNumber": phone}
        if friendly_name:
            data["FriendlyName"] = friendly_name[:64]
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._BASE}/{self._sid}/OutgoingCallerIds.json",
                auth=self._auth,
                data=data,
            )
            resp.raise_for_status()
            return resp.json().get("validation_code")

    async def _is_verified(self, client, phone: str) -> bool:  # pragma: no cover - live leg
        resp = await client.get(
            f"{self._BASE}/{self._sid}/OutgoingCallerIds.json",
            auth=self._auth,
            params={"PhoneNumber": phone},
        )
        resp.raise_for_status()
        return bool(resp.json().get("outgoing_caller_ids"))

    async def wait_until_verified(  # pragma: no cover - live leg
        self, phone: str, *, timeout: Optional[float] = None
    ) -> bool:
        import time

        import httpx

        deadline = time.monotonic() + (timeout if timeout is not None else self._wait_timeout)
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                try:
                    if await self._is_verified(client, phone):
                        return True
                except Exception:
                    pass  # transient (rate limit / network) — keep polling until the deadline
                if time.monotonic() >= deadline:
                    return False
                await asyncio.sleep(self._poll_interval)


def build_caller_id_verifier() -> CallerIdVerifier:
    """The trial-demo verifier when `TWILIO_VERIFY_LEADS=1` and account creds are set, else
    the no-op. Gated behind an explicit flag (not just the presence of creds) so a PAID
    account — which has the same creds but does NOT use verified caller IDs — is never made
    to wait on a verification that will never complete. Optional `TWILIO_VERIFY_TIMEOUT`
    (seconds) tunes how long the dialer waits per lead."""
    enabled = os.getenv("TWILIO_VERIFY_LEADS", "").strip().lower() in {"1", "true", "yes"}
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    if enabled and sid and token:
        try:
            timeout = float(os.getenv("TWILIO_VERIFY_TIMEOUT", "180"))
        except ValueError:
            timeout = 180.0
        return TwilioCallerIdVerifier(sid, token, wait_timeout=timeout)
    return NullCallerIdVerifier()


def _stream_twiml(wss_url: str) -> str:
    # <Connect><Stream> is bidirectional: Twilio forks call audio to us AND plays back
    # what we send. (<Start><Stream> would be one-way.)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="{wss_url}"/></Connect></Response>'


class PhoneAudioTransport:
    """A `contracts.live_agent.AudioTransport` whose medium is a live Twilio call."""

    def __init__(
        self,
        *,
        to_number: str,
        from_number: str,
        public_wss_base: str,
        placer: CallPlacer,
        connect_timeout: float = 45.0,
    ) -> None:
        self._to = to_number
        self._from = from_number
        self._wss_base = public_wss_base.rstrip("/")
        self._placer = placer
        self._connect_timeout = connect_timeout

        self._token = secrets.token_urlsafe(16)
        self._ws: Optional[WebSocket] = None
        self._stream_sid: Optional[str] = None
        self._call_sid: Optional[str] = None
        self._ready = asyncio.Event()  # set once Twilio's `start` frame arrives
        self._incoming: "asyncio.Queue[Optional[bytes]]" = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._closed = False

    # ---- AudioTransport ---------------------------------------------------- #
    async def start(self) -> None:
        _PENDING[self._token] = self
        wss_url = f"{self._wss_base}/twilio/media/{self._token}"
        try:
            self._call_sid = await self._placer.place(
                to=self._to, from_=self._from, twiml=_stream_twiml(wss_url)
            )
            await asyncio.wait_for(self._ready.wait(), timeout=self._connect_timeout)
        except asyncio.TimeoutError as exc:
            _PENDING.pop(self._token, None)
            raise PhoneNotAnswered(
                f"Twilio media stream for {self._to} never connected within "
                f"{self._connect_timeout}s (no answer / busy)."
            ) from exc

    async def send_audio(self, pcm: bytes) -> None:
        """Agent audio (24 kHz PCM) -> caller (8 kHz μ-law over Twilio media frames)."""
        if self._closed or self._ws is None or self._stream_sid is None:
            return
        payload = base64.b64encode(live_to_phone(pcm)).decode("ascii")
        await self._safe_send(
            {"event": "media", "streamSid": self._stream_sid, "media": {"payload": payload}}
        )

    async def recv_audio(self) -> AsyncIterator[bytes]:
        """Caller audio (8 kHz μ-law) -> agent (16 kHz PCM). Ends when Twilio stops."""
        while True:
            frame = await self._incoming.get()
            if frame is None:
                return
            yield frame

    async def send_event(self, event: dict) -> None:
        return None  # no UI on a phone call

    async def cut_playback(self) -> None:
        """Barge-in / moderation: tell Twilio to drop whatever agent audio it has
        buffered so the agent stops speaking immediately."""
        if self._closed or self._ws is None or self._stream_sid is None:
            return
        await self._safe_send({"event": "clear", "streamSid": self._stream_sid})

    async def end(self) -> None:
        self._closed = True
        self._incoming.put_nowait(None)
        _PENDING.pop(self._token, None)
        if self._call_sid is not None:
            await self._placer.hangup(self._call_sid)

    # ---- fed by the media route -------------------------------------------- #
    async def serve(self, websocket: WebSocket) -> None:
        """Own Twilio's socket for the call's lifetime: read inbound frames onto the
        queue, decode `start`/`stop`. Called by the media route once Twilio connects."""
        self._ws = websocket
        try:
            while True:
                raw = await websocket.receive_text()
                await self._on_message(json.loads(raw))
        except (WebSocketDisconnect, RuntimeError, KeyError):
            pass
        finally:
            if not self._closed:
                self._incoming.put_nowait(None)  # Twilio hung up

    async def _on_message(self, msg: dict) -> None:
        event = msg.get("event")
        if event == "start":
            start = msg.get("start") or {}
            self._stream_sid = start.get("streamSid") or msg.get("streamSid")
            self._ready.set()
        elif event == "media":
            media = msg.get("media") or {}
            # Only the caller's audio drives the agent. If Twilio ever labels a track,
            # ignore anything but inbound so the agent never hears its own voice back.
            track = media.get("track")
            if track and track != "inbound":
                return
            payload = media.get("payload")
            if payload:
                ulaw = base64.b64decode(payload)
                self._incoming.put_nowait(phone_to_live(ulaw))
        elif event == "stop":
            self._incoming.put_nowait(None)

    async def _safe_send(self, obj: dict) -> None:
        if self._ws is None:
            return
        async with self._send_lock:
            try:
                await self._ws.send_text(json.dumps(obj))
            except Exception:
                self._closed = True


def create_twilio_media_router() -> APIRouter:
    """The public WS endpoint Twilio's <Stream> connects to. Demuxes by the one-time
    token in the path and hands the socket to the waiting `PhoneAudioTransport`."""
    router = APIRouter()

    @router.websocket("/twilio/media/{token}")
    async def twilio_media(websocket: WebSocket, token: str) -> None:
        await websocket.accept()
        transport = _PENDING.pop(token, None)
        if transport is None:
            await websocket.close(code=4404)
            return
        await transport.serve(websocket)

    return router


# --- env-gated construction --------------------------------------------------- #
def public_wss_base() -> Optional[str]:
    """The public wss origin Twilio dials our media stream on. Explicit PUBLIC_WSS_BASE
    wins; otherwise derive it from RENDER_EXTERNAL_HOSTNAME (Render sets this on every
    web service) so a Render deploy needs no manual URL — the value isn't even known
    until the service exists."""
    base = os.getenv("PUBLIC_WSS_BASE")
    if base:
        return base.rstrip("/")
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if host:
        return f"wss://{host}"
    return None


def twilio_configured() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID")
        and os.getenv("TWILIO_AUTH_TOKEN")
        and os.getenv("TWILIO_FROM_NUMBER")
        and public_wss_base()
    )


def build_phone_transport(to_number: str) -> PhoneAudioTransport:
    """Real Twilio transport from env. Raises if unconfigured (callers gate on
    `twilio_configured()`)."""
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    return PhoneAudioTransport(
        to_number=to_number,
        from_number=os.environ["TWILIO_FROM_NUMBER"],
        public_wss_base=public_wss_base() or "",
        placer=TwilioRestPlacer(sid, token),
    )
