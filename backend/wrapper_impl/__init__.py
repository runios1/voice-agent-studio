"""Workstream 6 — Gemini implementation of the provider-agnostic ModelWrapper.

Public surface: GeminiWrapper (the ModelWrapper impl), GeminiConfig (env-driven
settings), and ConfigError / WrapperUsageError. Provider SDK is imported only
within this package (D8/D9 boundary).
"""

from .config import ConfigError, GeminiConfig
from .gemini import GeminiWrapper, WrapperUsageError

__all__ = ["GeminiWrapper", "GeminiConfig", "ConfigError", "WrapperUsageError"]
