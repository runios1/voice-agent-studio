"""The seam to WS5 (Security / screening) — mocked here.

The gate does NOT contain screening logic; WS5 owns the Model-Armor/Lakera call
and the real detection of "does this free text touch a locked-guardrail domain?"
The gate only *calls* screening on prose fields and reacts to the verdict:

  * ``blocked`` — hard reject (screening_blocked). Used for text touching a
    locked-guardrail domain (disclosure / DNC / forbidden claims).
  * ``flagged`` — accept-but-flag merely-odd content (D-security decision 2). The
    mutation still applies; the caller gets a Notice to surface conversationally.
  * ``ok``      — accept silently.

`ScreeningPort` is the frozen shape WS2 depends on. `MockScreeningAdapter` is a
deterministic stand-in so the gate is fully testable before WS5 merges; it does
crude substring matching ONLY — the real classifier is WS5's job. When WS5 lands,
inject the real adapter into `AgentService`/`ConfigGate`; nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Verdict = Literal["ok", "blocked", "flagged"]


@dataclass
class ScreeningResult:
    verdict: Verdict
    message: str = ""          # conversational reason, surfaced by the caller
    domain: str | None = None  # which locked-guardrail domain, if blocked


class ScreeningPort(Protocol):
    """Every free-text mutation is screened through this. Implemented by WS5."""

    def screen_text(self, path: str, text: str) -> ScreeningResult: ...


@dataclass
class MockScreeningAdapter:
    """Deterministic stand-in for WS5. Substring matching only — NOT real safety.

    Defaults chosen so tests can exercise all three verdicts without depending on
    WS5's real heuristics. Both lists are lower-cased on comparison.
    """

    block_markers: list[str] = field(
        default_factory=lambda: [
            "ignore previous",
            "no ai disclosure",
            "don't disclose",
            "do not disclose",
            "call after midnight",
            "ignore do-not-call",
            "guarantee a refund",
            "promise a discount",
        ]
    )
    flag_markers: list[str] = field(default_factory=lambda: ["[flag]", "weird"])
    block_domains: dict[str, str] = field(
        default_factory=lambda: {
            "disclosure": "AI disclosure",
            "do-not-call": "Do-Not-Call",
            "midnight": "calling hours",
        }
    )

    def screen_text(self, path: str, text: str) -> ScreeningResult:
        low = text.lower()
        for marker in self.block_markers:
            if marker in low:
                domain = next((d for k, d in self.block_domains.items() if k in marker), None)
                return ScreeningResult(
                    verdict="blocked",
                    message="That wording touches a platform guardrail, so I can't set it here.",
                    domain=domain,
                )
        for marker in self.flag_markers:
            if marker in low:
                return ScreeningResult(
                    verdict="flagged",
                    message="Saved — flagging that wording for a quick human check.",
                )
        return ScreeningResult(verdict="ok")
