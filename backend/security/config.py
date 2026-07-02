"""
Screening configuration + env loading.

Secrets (Model Armor API key, GCP project) are read from the environment and
NEVER committed or logged (conventions in CLAUDE.md §9). This module only reads
env; it does not hold the values in the repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# Env var names — values live only in the environment / a local .env (gitignored).
ENV_API_KEY = "MODEL_ARMOR_API_KEY"
ENV_PROJECT = "GOOGLE_CLOUD_PROJECT"
ENV_LOCATION = "MODEL_ARMOR_LOCATION"
ENV_TEMPLATE = "MODEL_ARMOR_TEMPLATE"
ENV_ENDPOINT = "MODEL_ARMOR_ENDPOINT"  # override for testing / regional endpoints


@dataclass(frozen=True)
class ScreeningConfig:
    """Tunables for the screening layer.

    `timeout_seconds` bounds the synchronous, inline screen call (grill decision:
    sync inline with per-call timeout). A timeout is treated as "screener
    unavailable" and handed to the fail-open/fail-closed policy — it never silently
    passes as clean.
    """

    timeout_seconds: float = 2.5
    # Fail-closed on locked-guardrail domains, fail-open elsewhere (grill decision).
    fail_closed_on_guardrail_domain: bool = True
    # If the external screener is unavailable, non-guardrail content is accepted-but-
    # flagged (fail-open) rather than blocked, so a screener outage can't halt the app.
    fail_open_on_unavailable: bool = True

    @staticmethod
    def from_env() -> "ScreeningConfig":
        cfg = ScreeningConfig()
        raw = os.getenv("SCREENING_TIMEOUT_SECONDS")
        if raw:
            try:
                cfg = ScreeningConfig(timeout_seconds=float(raw))
            except ValueError:
                pass
        return cfg


@dataclass(frozen=True)
class ModelArmorSettings:
    """Connection details for the real Model Armor REST screener, from env."""

    api_key: str
    project: str
    location: str
    template: str
    endpoint: str

    @staticmethod
    def from_env() -> "ModelArmorSettings | None":
        """Return settings if the required env is present, else None (use the mock)."""
        api_key = os.getenv(ENV_API_KEY)
        project = os.getenv(ENV_PROJECT)
        template = os.getenv(ENV_TEMPLATE)
        if not (api_key and project and template):
            return None
        location = os.getenv(ENV_LOCATION, "us-central1")
        endpoint = os.getenv(
            ENV_ENDPOINT,
            f"https://modelarmor.{location}.rep.googleapis.com",
        )
        return ModelArmorSettings(
            api_key=api_key,
            project=project,
            location=location,
            template=template,
            endpoint=endpoint,
        )
