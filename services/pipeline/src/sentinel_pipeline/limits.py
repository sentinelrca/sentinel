"""Tier-based limits with guarded sentinel-engine override.

When sentinel-engine is installed (hosted SaaS / licensed self-host), its
limit functions are used — limits differ per tier and are not visible in OSS
source. When absent, free-tier limits apply for all tiers regardless of
workspace.tier.
"""

from __future__ import annotations

_FREE_LIMITS = {
    "imports_per_week": 3,
    "traces_per_import": 500,
    "max_sources": 1,  # free tier: one connected source
    "retention_days": 7,  # free tier: 7-day span retention
}

_PAID_LIMITS = {
    "imports_per_week": None,  # unlimited
    "traces_per_import": 5_000,
    "max_sources": None,  # unlimited
    "retention_days": 30,
}

try:
    from sentinel_engine.limits import get_import_limits as _engine_get_limits
    from sentinel_engine.limits import get_tier_limits as _engine_get_tier_limits

    def get_import_limits(tier: int) -> dict:
        return _engine_get_limits(tier)

    def get_tier_limits(tier: int) -> dict:
        return _engine_get_tier_limits(tier)

except ImportError:

    def get_import_limits(tier: int) -> dict:  # type: ignore[misc]
        return dict(_FREE_LIMITS)

    def get_tier_limits(tier: int) -> dict:  # type: ignore[misc]
        """Return all limits for a given tier. Free tier for all in OSS mode."""
        if tier == 0:
            return dict(_FREE_LIMITS)
        return dict(_PAID_LIMITS)
