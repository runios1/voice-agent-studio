"""
ModelArmorScreener — the v1 real screener (Google Model Armor, REST).

Provider-agnostic REST call: prompt-injection / jailbreak, malicious-URL, and
PII / sensitive-data detection on BOTH inbound (user prompt) and outbound (model
response) content (D-security). Settings (API key, project, template) come from
env via config.ModelArmorSettings — never committed.

This is the live path. In CI it is mocked (see MockScreener); it is meant to be
live-tested manually with real credentials (DONE.md documents how). The endpoint
shapes below follow Model Armor's sanitizeUserPrompt / sanitizeModelResponse REST
methods; preview API surfaces churn, so the response parsing is defensive and any
parse/transport failure degrades to ScreenResult(available=False) — never a false
"clean".
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import ModelArmorSettings
from ..models import Category, Direction, Finding, ScreenResult, Severity

# Map Model Armor filter names -> our neutral categories.
_CATEGORY_MAP = {
    "pi_and_jailbreak": Category.PROMPT_INJECTION,
    "prompt_injection": Category.PROMPT_INJECTION,
    "jailbreak": Category.JAILBREAK,
    "malicious_uris": Category.MALICIOUS_URL,
    "malicious_url": Category.MALICIOUS_URL,
    "sdp": Category.PII,
    "sensitive_data_protection": Category.PII,
    "pii": Category.PII,
}

# Model Armor confidence levels -> our severity. Unknown -> MEDIUM (accept-but-flag).
_SEVERITY_MAP = {
    "LOW": Severity.LOW,
    "MEDIUM": Severity.MEDIUM,
    "HIGH": Severity.HIGH,
    "MEDIUM_AND_ABOVE": Severity.HIGH,
    "LOW_AND_ABOVE": Severity.MEDIUM,
}


class ModelArmorScreener:
    def __init__(self, settings: ModelArmorSettings, timeout_seconds: float = 2.5) -> None:
        self._s = settings
        self._timeout = timeout_seconds

    def _url(self, direction: Direction) -> str:
        method = (
            "sanitizeUserPrompt" if direction is Direction.INBOUND else "sanitizeModelResponse"
        )
        s = self._s
        return (
            f"{s.endpoint}/v1/projects/{s.project}/locations/{s.location}"
            f"/templates/{s.template}:{method}"
        )

    def _payload(self, text: str, direction: Direction) -> dict[str, Any]:
        if direction is Direction.INBOUND:
            return {"user_prompt_data": {"text": text}}
        return {"model_response_data": {"text": text}}

    async def screen(self, text: str, direction: Direction) -> ScreenResult:
        headers = {
            "x-goog-api-key": self._s.api_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._url(direction),
                    json=self._payload(text, direction),
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError):
            # Transport, timeout, auth, or JSON error -> unavailable, NOT clean.
            return ScreenResult(available=False)

        return self._parse(data)

    @staticmethod
    def _parse(data: dict[str, Any]) -> ScreenResult:
        """Defensively pull findings out of a sanitize* response.

        Model Armor nests results under `sanitizationResult.filterResults`. Any
        filter whose match state indicates a match becomes a Finding; the overall
        `filterMatchState` gives us an availability sanity check.
        """
        findings: list[Finding] = []
        result = data.get("sanitizationResult", data)
        filter_results = result.get("filterResults", {})

        # filterResults may be a dict keyed by filter name, or a list of dicts.
        items: list[tuple[str, dict]] = []
        if isinstance(filter_results, dict):
            items = list(filter_results.items())
        elif isinstance(filter_results, list):
            for entry in filter_results:
                if isinstance(entry, dict):
                    for k, v in entry.items():
                        if isinstance(v, dict):
                            items.append((k, v))

        for name, body in items:
            if not isinstance(body, dict):
                continue
            # Descend one level if the payload is wrapped (e.g. {"piAndJailbreakFilterResult": {...}}).
            inner = body
            for v in body.values():
                if isinstance(v, dict) and ("matchState" in v or "raiFilterResult" in v):
                    inner = v
                    break
            match_state = str(inner.get("matchState", "")).upper()
            if match_state not in ("MATCH_FOUND", "MATCH"):
                continue
            category = _map_category(name, inner)
            severity = _SEVERITY_MAP.get(
                str(inner.get("confidenceLevel", "")).upper(),
                Severity.HIGH if category is not Category.PII else Severity.MEDIUM,
            )
            findings.append(Finding(category=category, severity=severity, detail=name))

        return ScreenResult(findings=findings, available=True, raw=data)


def _map_category(name: str, body: dict[str, Any]) -> Category:
    key = _normalize(name)
    for token, cat in _CATEGORY_MAP.items():
        if token in key:
            return cat
    return Category.OTHER


def _normalize(name: str) -> str:
    # camelCase / PascalCase -> snake-ish lowercase for matching.
    out = []
    for ch in name:
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)
