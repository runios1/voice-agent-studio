"""EngineConfig.from_dict — the seam for future per-tenant/DB-loaded policy."""

from backend.autopause.config import EngineConfig


def test_defaults_are_sane():
    cfg = EngineConfig.default()
    assert cfg.guardrail_trip.enabled
    assert cfg.guardrail_trip.threshold == 3
    assert cfg.critical_guardrail.enabled


def test_from_dict_merges_nested_and_scalars():
    cfg = EngineConfig.from_dict(
        {
            "guardrail_trip": {"threshold": 5, "window_seconds": 120},
            "autopause_cooldown_seconds": 60,
        }
    )
    assert cfg.guardrail_trip.threshold == 5
    assert cfg.guardrail_trip.window_seconds == 120
    assert cfg.guardrail_trip.enabled is True  # untouched field keeps default
    assert cfg.autopause_cooldown_seconds == 60
    # unspecified sections keep their defaults
    assert cfg.escalation_spike.threshold == 3


def test_from_dict_ignores_unknown_keys():
    # A newer policy blob with keys this engine version doesn't know must not crash.
    cfg = EngineConfig.from_dict(
        {"guardrail_trip": {"threshold": 2, "future_flag": True}, "mystery": 1}
    )
    assert cfg.guardrail_trip.threshold == 2
