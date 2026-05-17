"""Unit tests for sentinel_pipeline.limits — guarded import of sentinel-engine."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock


def _reload_limits_module():
    """Remove cached module so each test gets a clean import."""
    for key in list(sys.modules.keys()):
        if key in ("sentinel_pipeline.limits", "sentinel_engine", "sentinel_engine.limits"):
            del sys.modules[key]


def test_free_tier_limits_when_engine_absent():
    """When sentinel-engine is not installed, all tiers get free-tier limits."""
    _reload_limits_module()
    sys.modules["sentinel_engine"] = None  # type: ignore[assignment]
    sys.modules["sentinel_engine.limits"] = None  # type: ignore[assignment]

    try:
        from sentinel_pipeline.limits import get_import_limits

        for tier in (0, 1, 2, 99):
            limits = get_import_limits(tier)
            assert limits["imports_per_week"] == 3
            assert limits["traces_per_import"] == 500
    finally:
        _reload_limits_module()


def test_free_tier_limits_are_independent_copies():
    """Each call returns a fresh dict — mutating one must not affect the next."""
    _reload_limits_module()
    sys.modules["sentinel_engine"] = None  # type: ignore[assignment]
    sys.modules["sentinel_engine.limits"] = None  # type: ignore[assignment]

    try:
        from sentinel_pipeline.limits import get_import_limits

        a = get_import_limits(0)
        a["imports_per_week"] = 999
        b = get_import_limits(0)
        assert b["imports_per_week"] == 3
    finally:
        _reload_limits_module()


def test_engine_limits_used_when_engine_present():
    """When sentinel-engine is installed, its get_import_limits is called."""
    _reload_limits_module()

    mock_engine_limits = MagicMock()
    mock_engine_limits.get_import_limits.return_value = {
        "imports_per_week": None,
        "traces_per_import": None,
    }

    mock_engine = MagicMock()
    mock_engine.limits = mock_engine_limits

    sys.modules["sentinel_engine"] = mock_engine
    sys.modules["sentinel_engine.limits"] = mock_engine_limits

    try:
        from sentinel_pipeline.limits import get_import_limits

        result = get_import_limits(1)
        assert result["imports_per_week"] is None
        mock_engine_limits.get_import_limits.assert_called_once_with(1)
    finally:
        _reload_limits_module()
