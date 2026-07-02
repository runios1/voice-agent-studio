"""
Core types for the screening layer (Workstream 5).

These describe *what a screener found* and *what we decided to do about it* —
kept separate on purpose:

  * a `Screener` (Model Armor, Lakera, mock) reports neutral findings — it does
    not know our product's guardrails;
  * the `policy` layer turns findings (+ our own locked-guardrail-domain detection)
    into a `Decision`.

Nothing here imports a provider SDK or a screener client — those live behind the
`Screener` interface (see screeners/). This module is pure data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Direction(str, Enum):
    """Which edge of the model boundary the content is crossing."""

    INBOUND = "inbound"    # user/tool text going INTO a model
    OUTBOUND = "outbound"  # model text/args coming OUT of a model


class Category(str, Enum):
    """Neutral finding categories a screener may report.

    The first four are what off-the-shelf screeners (Model Armor / Lakera)
    detect. GUARDRAIL_DOMAIN is OUR concept — free text that tries to subvert a
    locked platform guardrail (disclosure / DNC / forbidden claims). It is not
    reported by the external screener; the local detector in guardrail_domains.py
    raises it.
    """

    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    MALICIOUS_URL = "malicious_url"
    PII = "pii"
    GUARDRAIL_DOMAIN = "guardrail_domain"
    OTHER = "other"


class Severity(str, Enum):
    """How dangerous a finding is. Drives block-vs-flag in policy.py."""

    LOW = "low"        # merely-odd; accept-but-flag (don't police creativity)
    MEDIUM = "medium"
    HIGH = "high"      # dangerous; hard-block


class Decision(str, Enum):
    """The screening layer's verdict for a piece of content."""

    ACCEPT = "accept"  # clean
    FLAG = "flag"      # accept-but-flag: let it through, record it (screening_flagged)
    BLOCK = "block"    # hard-block (screening_blocked)


@dataclass
class Finding:
    category: Category
    severity: Severity
    detail: str = ""


@dataclass
class ScreenResult:
    """What a `Screener` reports for one piece of text. Neutral — no policy yet.

    `available=False` means the screener could not run (timeout / network / auth).
    The policy layer decides fail-open vs fail-closed from this flag; a screener
    NEVER silently reports "clean" when it actually failed to run.
    """

    findings: list[Finding] = field(default_factory=list)
    available: bool = True
    raw: Optional[dict[str, Any]] = None

    @property
    def flagged(self) -> bool:
        return bool(self.findings)


# API error-shape kinds (contracts/api/api_contract.md). Decisions map to these so
# WS2 (config gate) / WS3 (builder) can surface the contract's typed error / notice.
ERROR_KIND_BLOCKED = "screening_blocked"
ERROR_KIND_FLAGGED = "screening_flagged"


@dataclass
class ScreenDecision:
    """The policy layer's output. Consumed by the decorator and by the gate helper.

    * BLOCK -> the decorator raises `ScreeningBlocked`; the gate returns a typed
      `screening_blocked` error and does NOT apply the mutation.
    * FLAG  -> content is accepted; caller may surface a `screening_flagged` notice.
    * ACCEPT-> nothing to do.
    """

    decision: Decision
    direction: Direction
    findings: list[Finding] = field(default_factory=list)
    message: str = ""

    @property
    def blocked(self) -> bool:
        return self.decision is Decision.BLOCK

    @property
    def error_kind(self) -> Optional[str]:
        if self.decision is Decision.BLOCK:
            return ERROR_KIND_BLOCKED
        if self.decision is Decision.FLAG:
            return ERROR_KIND_FLAGGED
        return None

    @property
    def categories(self) -> list[str]:
        return [f.category.value for f in self.findings]
