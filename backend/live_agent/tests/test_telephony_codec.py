"""μ-law codec + resampling: round-trip fidelity and rate correctness."""

from __future__ import annotations

import array
import math

from backend.live_agent.telephony_codec import (
    live_to_phone,
    phone_to_live,
    pcm16_to_ulaw,
    resample_pcm16,
    ulaw_to_pcm16,
)


def _sine(hz: int, rate: int, ms: int, amp: int = 12000) -> bytes:
    n = rate * ms // 1000
    a = array.array("h", (int(amp * math.sin(2 * math.pi * hz * i / rate)) for i in range(n)))
    return a.tobytes()


def _rms(pcm: bytes) -> float:
    a = array.array("h")
    a.frombytes(pcm)
    if not a:
        return 0.0
    return math.sqrt(sum(x * x for x in a) / len(a))


def test_ulaw_roundtrip_is_close_for_a_tone():
    pcm = _sine(440, 8000, 100)
    back = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
    assert len(back) == len(pcm)
    # μ-law is lossy but the encode table is the exact inverse of decode, so error is
    # bounded by the quantization step — the reconstructed tone keeps ~full energy.
    assert _rms(back) > 0.8 * _rms(pcm)


def test_ulaw_encode_is_one_byte_per_sample():
    pcm = _sine(300, 8000, 20)
    ulaw = pcm16_to_ulaw(pcm)
    assert len(ulaw) == len(pcm) // 2  # 16-bit samples -> 1 μ-law byte each


def test_silence_maps_cleanly():
    silence = b"\x00\x00" * 160
    ulaw = pcm16_to_ulaw(silence)
    assert _rms(ulaw_to_pcm16(ulaw)) < 10  # ~silent back


def test_resample_changes_length_by_the_ratio():
    pcm8k = _sine(300, 8000, 100)  # 800 samples
    up = resample_pcm16(pcm8k, 8000, 16000)
    assert abs(len(up) // 2 - 1600) <= 2
    down = resample_pcm16(_sine(300, 24000, 100), 24000, 8000)  # 2400 -> 800
    assert abs(len(down) // 2 - 800) <= 2
    assert resample_pcm16(pcm8k, 8000, 8000) == pcm8k  # no-op


def test_full_phone_bridge_roundtrip_preserves_the_signal():
    """24 kHz Live audio -> phone μ-law -> back up to 16 kHz Live input keeps energy
    and the right rate (the exact hot path, minus Twilio)."""
    live_out = _sine(300, 24000, 200)
    ulaw = live_to_phone(live_out)  # -> 8 kHz μ-law
    assert len(ulaw) == 24000 * 200 // 1000 // 3  # 24k->8k, one byte per sample
    live_in = phone_to_live(ulaw)  # -> 16 kHz PCM
    assert abs(len(live_in) // 2 - 16000 * 200 // 1000) <= 4
    assert _rms(live_in) > 0.5 * _rms(resample_pcm16(live_out, 24000, 16000))
