"""Env-driven configuration for the Gemini wrapper.

Everything that might reasonably change without a code edit lives here and is read
from the environment, so pointing a tier at a different model, widening a timeout,
or moving from an AI-Studio key to Vertex is a config change — not a rewrite (D8).

Secrets are read from the environment at construction time and never logged or
committed (see repo .gitignore). A missing key surfaces as a clear config error at
construction, not a crash mid-call (D-reliability).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Tier -> model-id. All three default to gemini-3.5-flash (confirmed stable) and are
# independently overridable. When the frontier/voice tiers are pointed at their own
# models, only these env vars change. Preview model names churn — verify in the AI
# Studio console before overriding (CLAUDE.md §7).
_DEFAULT_MODEL = "gemini-3.5-flash"

_TIER_ENV = {
    "frontier": "GEMINI_MODEL_FRONTIER",
    "fast": "GEMINI_MODEL_FAST",
    "voice": "GEMINI_MODEL_VOICE",
}


class ConfigError(RuntimeError):
    """Raised when the wrapper cannot be configured (e.g. no API key)."""


def _resolve_models() -> dict[str, str]:
    return {tier: os.getenv(env, _DEFAULT_MODEL) for tier, env in _TIER_ENV.items()}


@dataclass
class GeminiConfig:
    """Resolved, immutable runtime configuration for one GeminiWrapper."""

    api_key: str
    models: dict[str, str] = field(default_factory=_resolve_models)
    timeout_s: float = 60.0
    max_retries: int = 2
    use_vertex: bool = False
    vertex_project: str | None = None
    vertex_location: str | None = None

    @classmethod
    def from_env(cls) -> "GeminiConfig":
        """Build config from the process environment.

        Key precedence: GEMINI_API_KEY then GOOGLE_API_KEY. Never hard-coded.
        """
        use_vertex = _envbool("GEMINI_USE_VERTEX") or _envbool("GOOGLE_GENAI_USE_VERTEXAI")
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""

        if not use_vertex and not api_key:
            raise ConfigError(
                "No Gemini API key found. Set GEMINI_API_KEY (or GOOGLE_API_KEY) "
                "in the environment, or set GEMINI_USE_VERTEX=1 with project/location. "
                "Never commit keys."
            )

        return cls(
            api_key=api_key,
            models=_resolve_models(),
            timeout_s=_envfloat("GEMINI_TIMEOUT_S", 60.0),
            max_retries=_envint("GEMINI_MAX_RETRIES", 2),
            use_vertex=use_vertex,
            vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            vertex_location=os.getenv("GOOGLE_CLOUD_LOCATION"),
        )

    def model_for(self, tier: str) -> str:
        """Map a tier name to its concrete model id; unknown tiers fall back to
        frontier so a caller typo degrades to the builder brain, not a crash."""
        return self.models.get(tier, self.models["frontier"])


def _envbool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _envint(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _envfloat(name: str, default: float) -> float:
    raw = os.getenv(name)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default
