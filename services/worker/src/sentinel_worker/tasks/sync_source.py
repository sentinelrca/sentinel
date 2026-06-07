from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import insert_spans
from sentinel_pipeline.db.postgres import engine, get_session, SourceRow, WorkspaceRow
from sentinel_pipeline.crypto import decrypt_config
from sentinel_pipeline.connectors import get_connector

logger = logging.getLogger(__name__)


@app.task(name="sync_source", bind=True, max_retries=3)
def sync_source(self, source_id: str) -> dict:
    try:
        engine.sync_engine.dispose()
        return asyncio.run(_sync_source(source_id))
    except Exception as exc:
        logger.exception("sync_source failed for source %s: %s", source_id, exc)
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


async def _sync_source(source_id: str) -> dict:
    # Load source and workspace in their own session, then close it before doing
    # network I/O. The cursor is updated in a separate session only after all
    # inserts succeed, so a mid-pull failure leaves the cursor unchanged and the
    # next retry re-fetches from the same point without corrupting ClickHouse.
    async with get_session() as session:
        source = await session.get(SourceRow, source_id)
        if not source:
            logger.warning("Source %s not found", source_id)
            return {"source_id": source_id, "spans": 0, "traces": 0}

        workspace = await session.get(WorkspaceRow, source.workspace_id)
        if workspace is None:
            logger.warning(
                "Workspace %s not found for source %s — skipping sync",
                source.workspace_id, source_id,
            )
            return {"source_id": source_id, "spans": 0, "traces": 0, "skipped": True}
        if workspace.tier < 1:
            logger.info(
                "Live sync skipped for free-tier workspace %s", source.workspace_id
            )
            return {"source_id": source_id, "spans": 0, "traces": 0, "skipped": True}

        workspace_id = str(source.workspace_id)
        workspace_tier = workspace.tier
        source_kind = source.kind
        config = decrypt_config(source.config_json)
        since = source.last_synced_at or datetime(2020, 1, 1, tzinfo=timezone.utc)

    connector = get_connector(source_kind)
    if not connector:
        logger.error("No connector registered for source kind '%s'", source_kind)
        return {"source_id": source_id, "spans": 0, "traces": 0}

    total_spans = 0
    trace_ids: set[str] = set()

    for batch in connector.pull(config, since=since, workspace_id=workspace_id):
        await asyncio.to_thread(insert_spans, batch)
        total_spans += len(batch)
        for span in batch:
            trace_ids.add(span.trace_id)

    # Advance the cursor only after all inserts succeed.
    async with get_session() as session:
        source = await session.get(SourceRow, source_id)
        if source:
            source.last_synced_at = datetime.now(timezone.utc)

    from sentinel_worker.tasks.process_trace import process_trace
    for trace_id in trace_ids:
        process_trace.delay(workspace_id, trace_id, workspace_tier)

    logger.info(
        "Synced source %s: %d spans across %d traces",
        source_id, total_spans, len(trace_ids),
    )
    return {"source_id": source_id, "spans": total_spans, "traces": len(trace_ids)}
