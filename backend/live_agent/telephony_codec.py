"""G.711 μ-law codec + PCM resampling for the Twilio phone bridge.

Twilio Media Streams carry 8 kHz mono μ-law (G.711) audio; Gemini Live wants 16 kHz
PCM s16le IN and emits 24 kHz PCM s16le OUT. This module is the pure, dependency-free
translation between the two — Python 3.13+ removed the stdlib `audioop`, so μ-law is
implemented here from the canonical G.711 tables. Everything operates on raw
little-endian PCM bytes / μ-law bytes and is cheap enough for the real-time path
(8 kHz = 160 samples per 20 ms Twilio frame).
"""

from __future__ import annotations

import array
import bisect
import sys

# --- G.711 μ-law (Sun reference constants) ---------------------------------- #
_BIAS = 0x84
_SIGN_BIT = 0x80
_QUANT_MASK = 0x0F
_SEG_MASK = 0x70
_SEG_SHIFT = 4


def _ulaw_to_linear(u_val: int) -> int:
    """One μ-law byte -> signed 16-bit sample (Sun `ulaw2linear`)."""
    u_val = ~u_val & 0xFF
    t = ((u_val & _QUANT_MASK) << 3) + _BIAS
    t <<= (u_val & _SEG_MASK) >> _SEG_SHIFT
    return (_BIAS - t) if (u_val & _SIGN_BIT) else (t - _BIAS)


# byte -> linear (256 entries) and the exact nearest-neighbour inverse (linear ->
# byte), built once from the decode table so encode/decode are guaranteed consistent.
_DECODE = [_ulaw_to_linear(i) for i in range(256)]


def _build_encode_table() -> bytes:
    pairs = sorted((v, b) for b, v in enumerate(_DECODE))
    vals = [p[0] for p in pairs]
    bytes_by_rank = [p[1] for p in pairs]
    n = len(vals)
    table = bytearray(65536)
    for s in range(-32768, 32768):
        idx = bisect.bisect_left(vals, s)
        candidates = [c for c in (idx - 1, idx) if 0 <= c < n]
        best = min(candidates, key=lambda c: abs(vals[c] - s))
        table[s & 0xFFFF] = bytes_by_rank[best]
    return bytes(table)


_ENCODE = _build_encode_table()


# --- byte plumbing ----------------------------------------------------------- #
def _to_int16(pcm: bytes) -> array.array:
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])
    if sys.byteorder != "little":  # PCM on the wire is little-endian
        a.byteswap()
    return a


def _from_int16(samples) -> bytes:
    a = array.array("h", (int(s) for s in samples))
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


# --- public codec ------------------------------------------------------------ #
def ulaw_to_pcm16(data: bytes) -> bytes:
    """8-bit μ-law -> 16-bit LE PCM."""
    return _from_int16(_DECODE[b] for b in data)


def pcm16_to_ulaw(pcm: bytes) -> bytes:
    """16-bit LE PCM -> 8-bit μ-law."""
    return bytes(_ENCODE[s & 0xFFFF] for s in _to_int16(pcm))


def resample_pcm16(pcm: bytes, src_hz: int, dst_hz: int) -> bytes:
    """Resample 16-bit LE PCM. Linear interpolation up; box-filter averaging down
    (which low-passes as it decimates — the same anti-alias posture as the mic path)."""
    if src_hz == dst_hz or not pcm:
        return pcm
    src = _to_int16(pcm)
    n = len(src)
    if n == 0:
        return b""

    if dst_hz > src_hz:
        m = int(n * dst_hz / src_hz)
        out = [0] * m
        for i in range(m):
            pos = i * src_hz / dst_hz
            i0 = int(pos)
            frac = pos - i0
            s0 = src[i0]
            s1 = src[min(i0 + 1, n - 1)]
            out[i] = int(s0 + (s1 - s0) * frac)
        return _from_int16(out)

    ratio = src_hz / dst_hz
    out = []
    ssum = 0
    cnt = 0
    need = ratio
    for s in src:
        ssum += s
        cnt += 1
        need -= 1
        if need <= 0:
            out.append(ssum // cnt)
            ssum = 0
            cnt = 0
            need += ratio
    if cnt:
        out.append(ssum // cnt)
    return _from_int16(out)


# --- the two conversions the transport actually uses ------------------------- #
def phone_to_live(ulaw_8k: bytes) -> bytes:
    """Twilio inbound (8 kHz μ-law) -> Gemini Live input (16 kHz PCM s16le)."""
    return resample_pcm16(ulaw_to_pcm16(ulaw_8k), 8000, 16000)


def live_to_phone(pcm_24k: bytes) -> bytes:
    """Gemini Live output (24 kHz PCM s16le) -> Twilio outbound (8 kHz μ-law)."""
    return pcm16_to_ulaw(resample_pcm16(pcm_24k, 24000, 8000))
