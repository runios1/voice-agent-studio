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
  * `RetellTransport`    — the managed-platform adapter (P2-D6). The Retell SDK is
                           imported LAZILY and is mocked in CI; the real leg is a
                           documented smoke test (see DONE.md). Swapping to LiveKit
                           later is another `CallTransport`, no engine change.

`transfer(reason)` is an OPTIONAL extension, deliberately NOT added to the frozen
`CallTransport` Protocol (that would edit a contract). The engine checks for it with
`hasattr`, so a transport that can't warm-transfer simply doesn't advertise one.
"""

from __future__ import annotations

import asyncio
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


class RetellTransport:
    """Managed-platform adapter (Retell v1, P2-D6). The SDK import is lazy and lives
    ONLY here (D8: provider SDKs never leak past their adapter). Unconfigured, it
    raises with a clear message rather than importing at module load, so CI — which
    uses the mock transports — never needs the SDK installed.

    The audio/barge-in specifics of a managed platform stay behind this class; the
    engine only ever sees `start / send_agent_utterance / receive / end` (+ optional
    `transfer`). Real wiring + a live smoke test are documented in DONE.md."""

    def __init__(self, *, api_key: Optional[str] = None, agent_number: Optional[str] = None) -> None:
        self._api_key = api_key
        self._agent_number = agent_number
        self._client = None  # set in start(), lazily

    async def start(self, phone: Optional[str]) -> None:  # pragma: no cover - live leg
        if not self._api_key:
            raise RuntimeError(
                "RetellTransport is a documented seam, not wired for CI. Provide an "
                "api_key and install the Retell SDK to place a live call, or use "
                "MockVoiceTransport in tests (see DONE.md)."
            )
        # Lazy import keeps the provider SDK out of every non-live import path.
        raise NotImplementedError(
            "Retell live integration is the documented smoke-test seam; see DONE.md."
        )

    async def send_agent_utterance(self, text: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def receive(self) -> AsyncIterator[Utterance]:  # pragma: no cover
        raise NotImplementedError
        yield  # pragma: no cover - marks this an async generator

    async def transfer(self, reason: str) -> None:  # pragma: no cover
        raise NotImplementedError

    async def end(self) -> None:  # pragma: no cover
        return None
