"""
Workstream 5 — Security / screening layer.

The OUTER layer of defense in depth (D-security): a probabilistic screener wrapped
around EVERY model in/out, plus a free-text screen the config gate calls on every
mutation. The layer *allowed to fail* — it reduces residual risk on top of the two
structural layers (can't-do-it / can't-know-it) owned by config_gate + runtime.

Public surface:
  * `ScreeningModelWrapper` — decorate any ModelWrapper (builder + runtime loops).
  * `screen_free_text`       — the config gate's per-mutation screen (WS2).
  * `Screener` + `MockScreener` / `ModelArmorScreener` — pluggable screener seam.
  * `ScreeningBlocked`       — typed hard-block exception (-> API `screening_blocked`).
  * `ScreenDecision`, `Decision`, `Direction`, `ScreeningConfig` — types + config.

Wiring (done by the integrator):
    from backend.security import ScreeningModelWrapper, build_screener
    wrapped = ScreeningModelWrapper(GeminiWrapper(...), build_screener())
"""

from __future__ import annotations

from .config import ModelArmorSettings, ScreeningConfig
from .decorator import ScreeningModelWrapper
from .errors import ScreeningBlocked
from .gate import screen_free_text
from .models import (
    Category,
    Decision,
    Direction,
    Finding,
    ScreenDecision,
    ScreenResult,
    Severity,
)
from .screener import Screener
from .screeners.mock import MockScreener
from .screeners.model_armor import ModelArmorScreener


def build_screener(config: ScreeningConfig | None = None) -> Screener:
    """Pick the screener from the environment: real Model Armor if its env is
    present, otherwise the deterministic MockScreener (safe default for dev/CI).

    NOTE: the mock is NOT a security control. Production MUST provide Model Armor
    credentials so this returns the real screener."""
    cfg = config or ScreeningConfig.from_env()
    settings = ModelArmorSettings.from_env()
    if settings is not None:
        return ModelArmorScreener(settings, timeout_seconds=cfg.timeout_seconds)
    return MockScreener()


__all__ = [
    "ScreeningModelWrapper",
    "screen_free_text",
    "build_screener",
    "Screener",
    "MockScreener",
    "ModelArmorScreener",
    "ScreeningBlocked",
    "ScreenDecision",
    "ScreenResult",
    "Decision",
    "Direction",
    "Category",
    "Severity",
    "Finding",
    "ScreeningConfig",
    "ModelArmorSettings",
]
