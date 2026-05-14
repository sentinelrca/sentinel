from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlparse

from clickhouse_driver import Client

from sentinel_pipeline.models.span import NormalizedSpan

logger = logging.getLogger(__name__)

_CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "clickhouse://localhost:9000/sentinel")

_CREATE_SPANS_TABLE = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id        String,
    span_id         String,
    parent_span_id  String DEFAULT '',
    workspace_id    String,
    name            String,
    kind            String,
    status          String,
    start_time      DateTime64(3, 'UTC'),
    end_time        DateTime64(3, 'UTC'),
    model           String DEFAULT '',
    agent_name      String DEFAULT '',
    input_tokens    Int64  DEFAULT 0,
    output_tokens   Int64  DEFAULT 0,
    retry_count     Int32  DEFAULT 0,
    error_message   String DEFAULT '',
    attributes_json String DEFAULT '{}'
) ENGINE = MergeTree()
ORDER BY (workspace_id, toDate(start_time), trace_id)
SETTINGS index_granularity = 8192;
"""


def _get_client() -> Client:
    parsed = urlparse(_CLICKHOUSE_URL)
    return Client(
        host=parsed.hostname or "localhost",
        port=parsed.port or 9000,
        database=parsed.path.lstrip("/") or "sentinel",
        send_receive_timeout=30,
    )


def ensure_tables() -> None:
    """Create ClickHouse tables if they don't exist. Called at worker startup."""
    try:
        client = _get_client()
        client.execute(_CREATE_SPANS_TABLE)
        logger.info("ClickHouse tables ready")
    except Exception:
        logger.exception("Failed to ensure ClickHouse tables")


def insert_spans(spans: list[NormalizedSpan]) -> None:
    """Bulk insert a batch of NormalizedSpan objects into ClickHouse."""
    if not spans:
        return
    try:
        client = _get_client()
        rows = [
            (
                s.trace_id,
                s.span_id,
                s.parent_span_id or "",
                s.workspace_id,
                s.name,
                s.kind.value,
                s.status.value,
                s.start_time,
                s.end_time,
                s.model or "",
                s.agent_name or "",
                s.input_tokens or 0,
                s.output_tokens or 0,
                s.retry_count,
                s.error_message or "",
                json.dumps(s.attributes),
            )
            for s in spans
        ]
        client.execute(
            "INSERT INTO spans VALUES",
            rows,
        )
    except Exception:
        logger.exception("Failed to insert %d spans", len(spans))
        raise


def insert_spans_dedup(spans: list[NormalizedSpan]) -> int:
    """Insert spans, skipping span_ids already present in ClickHouse. Returns new-row count."""
    if not spans:
        return 0
    client = _get_client()
    workspace_id = spans[0].workspace_id
    span_ids = [s.span_id for s in spans]
    try:
        existing_rows = client.execute(
            "SELECT DISTINCT span_id FROM spans "
            "WHERE workspace_id = %(ws)s AND span_id IN %(ids)s",
            {"ws": workspace_id, "ids": span_ids},
        )
        existing_ids = {row[0] for row in existing_rows}
    except Exception:
        logger.exception("Failed to check existing span_ids; proceeding with full insert")
        existing_ids = set()
    new_spans = [s for s in spans if s.span_id not in existing_ids]
    if new_spans:
        insert_spans(new_spans)
    return len(new_spans)


def fetch_trace_spans(trace_id: str, workspace_id: str) -> list[dict]:
    """Fetch all spans for a trace from ClickHouse. Returns raw dicts."""
    try:
        client = _get_client()
        rows = client.execute(
            "SELECT * FROM spans WHERE trace_id = %(trace_id)s "
            "AND workspace_id = %(workspace_id)s ORDER BY start_time",
            {"trace_id": trace_id, "workspace_id": workspace_id},
        )
        columns = [
            "trace_id", "span_id", "parent_span_id", "workspace_id",
            "name", "kind", "status", "start_time", "end_time",
            "model", "agent_name", "input_tokens", "output_tokens",
            "retry_count", "error_message", "attributes_json",
        ]
        return [dict(zip(columns, row)) for row in rows]
    except Exception:
        logger.exception("Failed to fetch spans for trace %s", trace_id)
        return []
