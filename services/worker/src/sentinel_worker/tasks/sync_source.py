from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import insert_spans
from sentinel_pipeline.db.postgres import get_session, SourceRow, WorkspaceRow
from sentinel_connectors.langfuse import LangfuseConnector

logger = logging.getLogger(__name__)

_CONNECTOR_MAP = {
    "langfuse": LangfuseConnector(),
}


@app.task(name="sync_source", bind=True, max_retries=3)
def sync_source(self, source_id: str) -> dict:
    try:
        return asyncio.run(_sync_source(source_id))
    except Exception as exc:
        logger.exception("sync_source failed for source %s: %s", source_id, exc)
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


async def _sync_source(source_id: str) -> dict:
    async with get_session() as session:
        source = await session.get(SourceRow, source_id)
        if not source:
            logger.warning("Source %s not found", source_id)
            return {"source_id": source_id, "spans": 0, "traces": 0}

        workspace = await session.get(WorkspaceRow, source.workspace_id)
        if workspace is None or workspace.tier < 1:
            logger.info(
                "Live sync skipped for free-tier workspace %s", source.workspace_id
            )
            return {"source_id": source_id, "spans": 0, "traces": 0, "skipped": True}

        connector = _CONNECTOR_MAP.get(source.kind)
        if not connector:
            logger.error("No connector registered for source kind '%s'", source.kind)
            return {"source_id": source_id, "spans": 0, "traces": 0}

        since = source.last_synced_at or datetime(2020, 1, 1, tzinfo=timezone.utc)
        config = source.config_json

        total_spans  = 0
        trace_ids:  set[str] = set()

        for batch in connector.pull(config, since=since, workspace_id=source.workspace_id):
            insert_spans(batch)
            total_spans += len(batch)
            for span in batch:
                trace_ids.add(span.trace_id)

        # Update the sync cursor
        source.last_synced_at = datetime.now(timezone.utc)

    # Queue process_trace for every new trace discovered
    from sentinel_worker.tasks.process_trace import process_trace
    for trace_id in trace_ids:
        process_trace.delay(source.workspace_id, trace_id)

    logger.info(
        "Synced source %s: %d spans across %d traces",
        source_id, total_spans, len(trace_ids),
    )
    return {"source_id": source_id, "spans": total_spans, "traces": len(trace_ids)}
