"""Outcome determination + two compliance/routing detectors.

`CallOutcome` (frozen) is what `run_call` returns and what drives the orchestrator's
per-lead lifecycle + the post-call workflows (P2-2/P2-4). Determination is layered so
the certain, code-owned outcomes never depend on a model:

  * BOOKED       — set the moment a `book_meeting` handler succeeds (in engine).
  * OPTED_OUT    — a DNC opt-out was detected in a lead turn (honored immediately, a
                   LOCKED guardrail — never negotiated).
  * TRANSFERRED  — a warm transfer happened (escalate()).
  * NO_ANSWER /
    VOICEMAIL    — a pre-conversation platform signal (transport.forced_outcome).
  * else         — classified from the transcript by an injected `OutcomeClassifier`.

The two detectors are deliberately simple keyword heuristics for v1, with a documented
seam to swap in a model/classifier. Opt-out detection is compliance-critical, so it
errs toward catching more (false positives just end a call politely; a false negative
would keep dialing someone who opted out).
"""

from __future__ import annotations

from typing import Protocol

from contracts.config_schema.schema import AgentConfig
from contracts.voice_runtime.interface import CallOutcome, Utterance

# --- opt-out (DNC) — err toward over-detection; a false positive only ends a call. ---
_OPT_OUT_PHRASES = (
    "do not call",
    "don't call",
    "dont call",
    "stop calling",
    "take me off",
    "remove me",
    "unsubscribe",
    "opt out",
    "opt me out",
    "no longer interested and stop",
    "never call",
    "lose my number",
    "leave me alone",
)

# --- explicit human handoff request -> warm transfer (P2-D6). ---
_HUMAN_REQUEST_PHRASES = (
    "speak to a human",
    "talk to a human",
    "speak to a person",
    "talk to a person",
    "real person",
    "speak to someone",
    "talk to someone real",
    "get me a manager",
    "speak to a representative",
    "talk to a representative",
    "transfer me",
    "speak to your manager",
)


def detect_opt_out(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _OPT_OUT_PHRASES)


def detect_human_request(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _HUMAN_REQUEST_PHRASES)


class OutcomeClassifier(Protocol):
    """Classifies a finished conversation into a qualification outcome. Swappable so a
    model-backed classifier (schema-constrained, D-reliability) can replace the v1
    heuristic without touching the engine."""

    def classify(self, config: AgentConfig, transcript: list[Utterance]) -> CallOutcome: ...


class HeuristicOutcomeClassifier:
    """v1 default: no model call. If the lead engaged at all, treat as QUALIFIED;
    a lead that never spoke is NO_ANSWER. This only runs AFTER the certain outcomes
    (booked / opted-out / transferred / platform no-answer) are ruled out, so it is a
    coarse fallback, not the compliance-critical path. Swap for a `ModelOutcome
    Classifier` (transcript -> schema-constrained label) at integration."""

    def classify(self, config: AgentConfig, transcript: list[Utterance]) -> CallOutcome:
        lead_turns = [u for u in transcript if u.speaker == "lead"]
        if not lead_turns:
            return CallOutcome.NO_ANSWER
        return CallOutcome.QUALIFIED
