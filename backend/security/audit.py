"""
Audit logging for screening decisions.

Every decision (accept / flag / block) is logged so blocks and flags are
observable in production. We log a CONTENT FINGERPRINT (a short salted-ish hash),
never the raw text — logs must not become a place where prompt-injection payloads
or PII (the very things we screen for) get re-leaked (CLAUDE.md §9 / D-security).
"""

from __future__ import annotations

import hashlib
import logging

from .models import Decision, Direction, ScreenDecision

logger = logging.getLogger("voice_agent_studio.security.screening")


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()[:12]


def log_decision(decision: ScreenDecision, text: str, *, context: str = "") -> None:
    """Emit one structured log line for a decision. Raw content is never logged."""
    level = {
        Decision.ACCEPT: logging.DEBUG,
        Decision.FLAG: logging.INFO,
        Decision.BLOCK: logging.WARNING,
    }[decision.decision]
    logger.log(
        level,
        "screening decision=%s direction=%s context=%s categories=%s len=%d fp=%s",
        decision.decision.value,
        decision.direction.value,
        context or "-",
        ",".join(decision.categories) or "-",
        len(text),
        _fingerprint(text),
    )


def log_unavailable(direction: Direction, *, context: str, error: str) -> None:
    logger.warning(
        "screener unavailable direction=%s context=%s error=%s",
        direction.value,
        context or "-",
        error,
    )
