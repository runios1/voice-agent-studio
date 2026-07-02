"""
The decision policy — turns neutral screener findings + our own guardrail-domain
detection into a `ScreenDecision` (accept / flag / block).

The rules (D-security, and the grill decisions):

  * Locked-guardrail-domain subversion (disclosure / DNC / forbidden claims):
    HARD-BLOCK. This is the platform's core value; it outranks everything.
  * A HIGH-severity screener finding (prompt injection, jailbreak, malicious URL):
    HARD-BLOCK.
  * A screener that is UNAVAILABLE (timeout / error):
      - fail-CLOSED if the content touches a guardrail domain (block),
      - fail-OPEN otherwise (accept-but-flag) so a screener outage can't take the
        product down. (grill decision)
  * Merely-odd, LOW/MEDIUM findings: ACCEPT-BUT-FLAG — don't police creativity.
  * Nothing found: ACCEPT.
"""

from __future__ import annotations

from .config import ScreeningConfig
from .guardrail_domains import detect_guardrail_domain
from .models import (
    Category,
    Decision,
    Direction,
    Finding,
    ScreenDecision,
    ScreenResult,
    Severity,
)

# Categories that are dangerous enough to hard-block on sight.
_BLOCK_CATEGORIES = {
    Category.PROMPT_INJECTION,
    Category.JAILBREAK,
    Category.MALICIOUS_URL,
    Category.GUARDRAIL_DOMAIN,
}

_BLOCK_MESSAGE = (
    "I can't set that up — it would cross one of the platform's safety rules "
    "(like AI disclosure, do-not-call, or promises we can't keep). "
    "Want to try phrasing it a different way?"
)
_UNAVAILABLE_BLOCK_MESSAGE = (
    "I couldn't safety-check that just now, and it touches a protected area, so "
    "I'm holding off. Please try again in a moment."
)


def decide(
    text: str,
    direction: Direction,
    screen_result: ScreenResult,
    config: ScreeningConfig,
) -> ScreenDecision:
    """Combine local guardrail detection with the external screener's findings."""

    guardrail_findings = detect_guardrail_domain(text)

    # 1. Our own locked-guardrail subversion always hard-blocks, regardless of the
    #    external screener's opinion or availability.
    if guardrail_findings:
        return ScreenDecision(
            decision=Decision.BLOCK,
            direction=direction,
            findings=guardrail_findings,
            message=_BLOCK_MESSAGE,
        )

    # 2. Screener unavailable: fail-closed only if guardrail-adjacent (handled
    #    above, so here we fail OPEN) — accept-but-flag so an outage isn't an outage.
    if not screen_result.available:
        if config.fail_open_on_unavailable:
            return ScreenDecision(
                decision=Decision.FLAG,
                direction=direction,
                findings=[
                    Finding(
                        category=Category.OTHER,
                        severity=Severity.LOW,
                        detail="screener unavailable; accepted-but-flagged (fail-open)",
                    )
                ],
                message="",
            )
        return ScreenDecision(
            decision=Decision.BLOCK,
            direction=direction,
            findings=[Finding(Category.OTHER, Severity.HIGH, "screener unavailable (fail-closed)")],
            message=_UNAVAILABLE_BLOCK_MESSAGE,
        )

    # 3. External screener findings.
    high = [f for f in screen_result.findings if f.severity is Severity.HIGH]
    block = [f for f in high if f.category in _BLOCK_CATEGORIES]
    if block:
        return ScreenDecision(
            decision=Decision.BLOCK,
            direction=direction,
            findings=screen_result.findings,
            message=_BLOCK_MESSAGE,
        )

    # 4. Anything else the screener noted is merely-odd -> accept-but-flag.
    if screen_result.findings:
        return ScreenDecision(
            decision=Decision.FLAG,
            direction=direction,
            findings=screen_result.findings,
            message="",
        )

    # 5. Clean.
    return ScreenDecision(decision=Decision.ACCEPT, direction=direction)
