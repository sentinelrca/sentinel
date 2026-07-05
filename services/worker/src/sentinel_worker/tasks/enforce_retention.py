"""enforce_retention — delete live spans older than each workspace's retention window.

Designed to run as a periodic Celery beat task (e.g. nightly). Iterates every
workspace, computes its retention cutoff from get_tier_limits(), and issues an
async ClickHouse DELETE mutation for expired spans.

Retention limits by tier (OSS mode — overridden by sentinel-engine when installed):
  FREE (0):       7 days
  STARTER+ (1+):  30 days
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from sentinel_pipeline.db.clickhouse import delete_spans_older_than
from sentinel_pipeline.db.postgres import WorkspaceRow, engine, get_session
from sentinel_pipeline.limits import get_tier_limits
from sentinel_worker.main import app

logger = logging.getLogger(__name__)


@app.task(name="enforce_retention")
def enforce_retention() -> dict:
    """Delete spans beyond each workspace's retention window.

    Safe to run multiple times — ClickHouse mutations are idempotent.
    """
    engine.sync_engine.dispose()
    return asyncio.run(_enforce_retention())


async def _enforce_retention() -> dict:
    async with get_session() as session:
        result = await session.execute(select(WorkspaceRow))
        workspaces = result.scalars().all()

    cleaned = 0
    errors = 0
    now = datetime.now(timezone.utc)

    for ws in workspaces:
        limits = get_tier_limits(ws.tier)
        retention_days: int | None = limits.get("retention_days")
        if retention_days is None:
            continue  # unlimited retention for this tier

        cutoff = now - timedelta(days=retention_days)
        cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            delete_spans_older_than(ws.id, cutoff_iso)
            cleaned += 1
        except Exception:
            logger.exception("Retention cleanup failed for workspace %s", ws.id)
            errors += 1

    logger.info("Retention enforcement done: %d workspaces cleaned, %d errors", cleaned, errors)
    return {"workspaces_cleaned": cleaned, "errors": errors}
