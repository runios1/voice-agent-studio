"""
`StreamModerator` (contracts/live_agent) — the output-moderation net around a Live
agent's speech.

Live streams `output_audio_transcription` as the agent's current utterance forms:
each delta re-sends the WHOLE utterance-so-far, not just the new fragment. The
session (P4-2) calls `check(cumulative_text)` on every delta and, on `BLOCK`,
`transport.cut_playback()`s the buffered audio (bounded by
`LiveAgentSpec.moderation_buffer_ms`, ~600ms) and steers the conversation back.

This screens that cumulative text through the SAME screener -> policy -> audit
pipeline as everything else in the app (`backend.security.engine.screen_text`), as
OUTBOUND content, so a spoken guardrail violation is judged by the identical rules
as a written one (D-security: one gate, not two). It is the "net", not the floor —
tools stay guarded and disclosure stays scripted in code regardless of what this
decides.

Two judgment calls, made explicit here rather than left implicit:

  * CUMULATIVE, not incremental — screening the growing whole (not just each new
    token) lets the policy layer see full phrases, which is where prompt-
    injection / jailbreak / guardrail-domain phrasing actually shows up. Screening
    every fragment would also blow the audio delay budget for no benefit.
  * DEBOUNCED — a real screener call takes real time, and it must return well
    inside the audio buffer. A check only actually calls the screener once the
    text has grown by `min_new_chars` OR `min_interval_s` has elapsed since the
    last screen; in between, the last verdict is returned. The very first
    non-empty text is always screened immediately (so a short utterance can't
    slip through purely for being under the growth threshold).

A `BLOCK` is sticky for the rest of the utterance — once cut, nothing later in the
same utterance can un-block it. A NEW utterance is detected when `cumulative_text`
is no longer an extension of the previous call's text (Live starts a fresh
transcription buffer per response turn); that resets debounce state and stickiness
so the next utterance is screened from scratch.
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from contracts.live_agent.interface import ModerationVerdict

from ..security.config import ScreeningConfig
from ..security.engine import screen_text
from ..security.models import Decision
from ..security.models import Direction as ScreenDirection
from ..security.screener import Screener

_VERDICT_BY_DECISION = {
    Decision.ACCEPT: ModerationVerdict.ALLOW,
    Decision.FLAG: ModerationVerdict.FLAG,
    Decision.BLOCK: ModerationVerdict.BLOCK,
}

DEFAULT_MIN_NEW_CHARS = 24
DEFAULT_MIN_INTERVAL_S = 0.25


class DebouncedStreamModerator:
    """`StreamModerator` backed by `backend.security`.

    One instance is created per call/session (it is handed to
    `LiveAgentSession.run` once) and reused across every agent turn in that
    call — internal state resets automatically at each new utterance.
    """

    def __init__(
        self,
        screener: Screener,
        *,
        config: Optional[ScreeningConfig] = None,
        min_new_chars: int = DEFAULT_MIN_NEW_CHARS,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        context: str = "live_agent:output",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._screener = screener
        self._config = config or ScreeningConfig.from_env()
        self._min_new_chars = min_new_chars
        self._min_interval_s = min_interval_s
        self._context = context
        self._clock = clock
        self._reset()

    def _reset(self) -> None:
        self._last_text = ""
        self._last_screened_len = 0
        self._last_check_time: Optional[float] = None
        self._last_verdict = ModerationVerdict.ALLOW

    async def check(self, cumulative_text: str) -> ModerationVerdict:
        if not cumulative_text.startswith(self._last_text):
            self._reset()  # discontinuity -> a new utterance started
        self._last_text = cumulative_text

        if self._last_verdict is ModerationVerdict.BLOCK:
            return ModerationVerdict.BLOCK  # sticky for the rest of this utterance

        if not cumulative_text.strip():
            return self._last_verdict

        now = self._clock()
        grew_enough = (len(cumulative_text) - self._last_screened_len) >= self._min_new_chars
        due = self._last_check_time is None or (now - self._last_check_time) >= self._min_interval_s
        if not (grew_enough or due):
            return self._last_verdict  # debounced: too soon, not enough new text

        self._last_screened_len = len(cumulative_text)
        self._last_check_time = now

        decision = await screen_text(
            self._screener,
            cumulative_text,
            ScreenDirection.OUTBOUND,
            self._config,
            context=self._context,
        )
        self._last_verdict = _VERDICT_BY_DECISION[decision.decision]
        return self._last_verdict


def build_stream_moderator(
    screener: Screener,
    *,
    config: Optional[ScreeningConfig] = None,
    moderation_buffer_ms: Optional[int] = None,
) -> DebouncedStreamModerator:
    """Construct the default `StreamModerator`, sizing the debounce interval to
    leave headroom inside the caller's audio buffer (`LiveAgentSpec.moderation_buffer_ms`)
    for the screener round-trip itself."""
    kwargs: dict = {"config": config}
    if moderation_buffer_ms is not None:
        kwargs["min_interval_s"] = min(DEFAULT_MIN_INTERVAL_S, moderation_buffer_ms / 1000 / 2)
    return DebouncedStreamModerator(screener, **kwargs)
