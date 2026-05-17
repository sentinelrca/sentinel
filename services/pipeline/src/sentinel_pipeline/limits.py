"""Import quota limits with guarded sentinel-engine override.

When sentinel-engine is installed (hosted SaaS / licensed self-host), its
get_import_limits() function is used — limits differ per tier and are not
visible in OSS source. When it is absent, free-tier limits apply for all
tiers regardless of the workspace.tier DB value.
"""
from __future__ import annotations

_FREE_LIMITS = {"imports_per_week": 3, "traces_per_import": 500}

try:
    from sentinel_engine.limits import get_import_limits as _engine_get_limits

    def get_import_limits(tier: int) -> dict:
        return _engine_get_limits(tier)

except ImportError:
    def get_import_limits(tier: int) -> dict:  # type: ignore[misc]
        return dict(_FREE_LIMITS)
