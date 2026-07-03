"""Backoff policy for no-answer follow-up cadence.

When a lead doesn't answer, the follow-up *touch* is spaced out with exponential
backoff and capped, and it stops entirely once the lead's attempts reach the
envelope's `max_attempts_per_lead` (campaign model). This is cadence for touches
(a nudge email); the actual re-dial is the orchestrator's RETRY state, not ours.
"""

from __future__ import annotations

from contracts.campaign.model import GuardrailEnvelope

_DEFAULT_MAX_ATTEMPTS = GuardrailEnvelope().max_attempts_per_lead


def backoff_seconds(attempts: int, *, base_seconds: int = 3600, cap_seconds: int = 86400) -> int:
    """Delay before the next touch. attempts=1 -> base, then doubles, capped.
    (base 1h, cap 24h by default.)"""
    n = max(attempts, 1)
    return min(base_seconds * (2 ** (n - 1)), cap_seconds)


def attempts_exhausted(attempts: int, max_attempts: int = _DEFAULT_MAX_ATTEMPTS) -> bool:
    return attempts >= max_attempts
