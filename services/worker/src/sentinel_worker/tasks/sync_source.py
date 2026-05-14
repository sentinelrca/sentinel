from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import insert_spans_dedup
from sentinel_pipeline.db.postgres import get_session, SourceRow
from sentinel_connectors.langfuse import LangfuseConnector
from sentinel_connectors.langsmith import LangSmithConnector

logger = logging.getLogger(__name__)

_CONNECTOR_MAP = {
    "langfuse":  LangfuseConnector(),
    "langsmith": LangSmithConnector(),
}

# Re-fetch this window before last_synced_at to catch late-arriving spans
_OVERLAP_WINDOW = timedelta(minutes=10)


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

        connector = _CONNECTOR_MAP.get(source.kind)
        if not connector:
            logger.error("No connector registered for source kind '%s'", source.kind)
            return {"source_id": source_id, "spans": 0, "traces": 0}

        # Compute query window: subtract overlap to catch late-arriving spans
        since_raw = source.last_synced_at or datetime(2020, 1, 1, tzinfo=timezone.utc)
        since = since_raw - _OVERLAP_WINDOW
        config = source.config_json

        # Advance the cursor BEFORE pulling. If inserts fail, next retry re-pulls
        # the overlap window and insert_spans_dedup skips already-present spans.
        source.last_synced_at = datetime.now(timezone.utc)
        workspace_id = source.workspace_id

    total_spans = 0
    trace_ids: set[str] = set()

    for batch in connector.pull(config, since=since, workspace_id=workspace_id):
        inserted = insert_spans_dedup(batch)
        total_spans += inserted
        for span in batch:
            trace_ids.add(span.trace_id)

    # Queue process_trace for every trace touched in this window
    from sentinel_worker.tasks.process_trace import process_trace
    for trace_id in trace_ids:
        process_trace.delay(workspace_id, trace_id)

    logger.info(
        "Synced source %s: %d new spans across %d traces (window: %s → now)",
        source_id, total_spans, len(trace_ids), since.isoformat(),
    )
    return {"source_id": source_id, "spans": total_spans, "traces": len(trace_ids)}
