"""Offline tests for the Model Armor screener: response parsing + fail-safe.

No network: we exercise the pure `_parse` mapping and the config gating. The live
round-trip is a manual smoke test (see DONE.md)."""

from __future__ import annotations

from backend.security.config import ModelArmorSettings
from backend.security.models import Category, Severity
from backend.security.screeners.model_armor import ModelArmorScreener


def test_parse_flags_prompt_injection_match():
    data = {
        "sanitizationResult": {
            "filterMatchState": "MATCH_FOUND",
            "filterResults": {
                "pi_and_jailbreak": {
                    "piAndJailbreakFilterResult": {
                        "matchState": "MATCH_FOUND",
                        "confidenceLevel": "HIGH",
                    }
                }
            },
        }
    }
    res = ModelArmorScreener._parse(data)
    assert res.available
    assert any(f.category is Category.PROMPT_INJECTION and f.severity is Severity.HIGH for f in res.findings)


def test_parse_maps_malicious_uri():
    data = {
        "sanitizationResult": {
            "filterResults": {
                "malicious_uris": {"maliciousUriFilterResult": {"matchState": "MATCH_FOUND", "confidenceLevel": "HIGH"}}
            }
        }
    }
    res = ModelArmorScreener._parse(data)
    assert any(f.category is Category.MALICIOUS_URL for f in res.findings)


def test_parse_no_match_is_clean_and_available():
    data = {
        "sanitizationResult": {
            "filterMatchState": "NO_MATCH_FOUND",
            "filterResults": {
                "pi_and_jailbreak": {"piAndJailbreakFilterResult": {"matchState": "NO_MATCH_FOUND"}}
            },
        }
    }
    res = ModelArmorScreener._parse(data)
    assert res.available
    assert res.findings == []


def test_settings_from_env_absent(monkeypatch):
    for k in ("MODEL_ARMOR_API_KEY", "GOOGLE_CLOUD_PROJECT", "MODEL_ARMOR_TEMPLATE"):
        monkeypatch.delenv(k, raising=False)
    assert ModelArmorSettings.from_env() is None


def test_settings_from_env_present(monkeypatch):
    monkeypatch.setenv("MODEL_ARMOR_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("MODEL_ARMOR_TEMPLATE", "tmpl")
    s = ModelArmorSettings.from_env()
    assert s and s.project == "proj" and s.template == "tmpl"
    screener = ModelArmorScreener(s)
    from backend.security.models import Direction
    url = screener._url(Direction.INBOUND)
    assert "projects/proj/locations/" in url and url.endswith(":sanitizeUserPrompt")
