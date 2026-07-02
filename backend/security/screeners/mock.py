"""
MockScreener — a deterministic, offline screener for CI and tests.

It is a small heuristic stand-in for Model Armor: it recognises well-known
prompt-injection / jailbreak phrasings and obviously-malicious URLs. It is NOT a
security control — it exists so the policy/decorator/gate logic can be exercised
without a network call (DONE_CRITERIA: "Screener API may be mocked in CI").

Two knobs make failure-path tests trivial:
  * `unavailable=True`  -> always returns ScreenResult(available=False);
  * `extra_injection_markers` -> add phrases that should trip PROMPT_INJECTION.
"""

from __future__ import annotations

import re

from ..models import Category, Direction, Finding, ScreenResult, Severity

_INJECTION_MARKERS = [
    r"ignore (?:all |the )?(?:previous|above|prior) instructions",
    r"disregard (?:all |your )?(?:previous|prior) (?:instructions|prompt)",
    r"you are now (?:in )?(?:developer|dan|jailbreak) mode",
    r"reveal your (?:system )?prompt",
    r"print your (?:system )?prompt",
    r"forget (?:everything|all your rules)",
    r"pretend you have no restrictions",
    r"act as (?:dan|an unrestricted)",
]

# Deliberately crude: a couple of well-known bad hosts + a nonexistent TLD used in
# tests. Real malicious-URL intelligence is Model Armor's job.
_MALICIOUS_URL_MARKERS = [
    r"https?://(?:\S+\.)?(?:malware|phishing|evil-corp|badsite)\b\S*",
    r"https?://\S+\.(?:xyz-phish|malware-test)\b\S*",
    r"bit\.ly/evil\S*",
]

_PII_MARKERS = [
    r"\b\d{3}-\d{2}-\d{4}\b",                         # US SSN
    r"\b(?:\d[ -]*?){13,16}\b",                       # card-ish number run
]


class MockScreener:
    def __init__(
        self,
        *,
        unavailable: bool = False,
        extra_injection_markers: list[str] | None = None,
    ) -> None:
        self._unavailable = unavailable
        markers = _INJECTION_MARKERS + list(extra_injection_markers or [])
        self._injection = [re.compile(m, re.IGNORECASE) for m in markers]
        self._malicious_url = [re.compile(m, re.IGNORECASE) for m in _MALICIOUS_URL_MARKERS]
        self._pii = [re.compile(m) for m in _PII_MARKERS]

    async def screen(self, text: str, direction: Direction) -> ScreenResult:
        if self._unavailable:
            return ScreenResult(available=False)

        findings: list[Finding] = []
        if any(rx.search(text) for rx in self._injection):
            findings.append(Finding(Category.PROMPT_INJECTION, Severity.HIGH, "injection phrasing"))
        if any(rx.search(text) for rx in self._malicious_url):
            findings.append(Finding(Category.MALICIOUS_URL, Severity.HIGH, "known-bad URL"))
        if any(rx.search(text) for rx in self._pii):
            # PII is sensitive but not itself an attack -> medium, accept-but-flag.
            findings.append(Finding(Category.PII, Severity.MEDIUM, "possible PII"))
        return ScreenResult(findings=findings, available=True)
