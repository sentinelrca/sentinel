from __future__ import annotations

import json
import logging
import os
from datetime import datetime
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

_CREATE_PROJECT_SPANS_TABLE = """
CREATE TABLE IF NOT EXISTS project_spans (
    project_id      String,
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
ORDER BY (project_id, trace_id, span_id)
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
        client.execute(_CREATE_PROJECT_SPANS_TABLE)
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


def count_distinct_traces(workspace_id: str) -> int:
    """Count distinct trace_ids for a workspace."""
    try:
        client = _get_client()
        rows = client.execute(
            "SELECT count(DISTINCT trace_id) FROM spans WHERE workspace_id = %(ws)s",
            {"ws": workspace_id},
        )
        return rows[0][0] if rows else 0
    except Exception:
        logger.exception("Failed to count distinct traces for workspace %s", workspace_id)
        return 0


def fetch_trace_stats_batch(trace_ids: list[str], workspace_id: str) -> dict[str, dict]:
    """Return span stats keyed by trace_id: span_count, llm_calls, total_ms."""
    if not trace_ids:
        return {}
    try:
        client = _get_client()
        rows = client.execute(
            "SELECT trace_id, "
            "  count() AS span_count, "
            "  countIf(kind = 'llm_call') AS llm_calls, "
            "  dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
            "FROM spans "
            "WHERE workspace_id = %(ws)s AND trace_id IN %(ids)s "
            "GROUP BY trace_id",
            {"ws": workspace_id, "ids": tuple(trace_ids)},
        )
        return {
            row[0]: {"span_count": row[1], "llm_calls": row[2], "total_ms": row[3]}
            for row in rows
        }
    except Exception:
        logger.exception("Failed to fetch trace stats batch")
        return {}


def insert_project_spans(project_id: str, spans: list[NormalizedSpan]) -> None:
    """Bulk insert spans into project_spans for a specific project."""
    if not spans:
        return
    try:
        client = _get_client()
        rows = [
            (
                project_id,
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
        client.execute("INSERT INTO project_spans VALUES", rows)
    except Exception:
        logger.exception("Failed to insert %d project spans for project %s", len(spans), project_id)
        raise


def fetch_project_spans(project_id: str, workspace_id: str) -> list[dict]:
    """Fetch all spans for a project snapshot from ClickHouse."""
    try:
        client = _get_client()
        rows = client.execute(
            "SELECT project_id, trace_id, span_id, parent_span_id, workspace_id, "
            "name, kind, status, start_time, end_time, model, agent_name, "
            "input_tokens, output_tokens, retry_count, error_message, attributes_json "
            "FROM project_spans "
            "WHERE project_id = %(project_id)s AND workspace_id = %(workspace_id)s "
            "ORDER BY trace_id, start_time",
            {"project_id": project_id, "workspace_id": workspace_id},
        )
        columns = [
            "project_id", "trace_id", "span_id", "parent_span_id", "workspace_id",
            "name", "kind", "status", "start_time", "end_time",
            "model", "agent_name", "input_tokens", "output_tokens",
            "retry_count", "error_message", "attributes_json",
        ]
        return [dict(zip(columns, row)) for row in rows]
    except Exception:
        logger.exception("Failed to fetch project spans for project %s", project_id)
        return []


def delete_project_spans(project_id: str, workspace_id: str) -> None:
    """Delete all spans for a project from ClickHouse. Called on project delete.

    Uses ALTER TABLE ... DELETE (a ClickHouse mutation). Mutations are asynchronous —
    this call returns before data is physically removed. Safe for fire-and-forget cleanup
    but not suitable for read-after-delete scenarios.
    """
    try:
        client = _get_client()
        client.execute(
            "ALTER TABLE project_spans DELETE "
            "WHERE project_id = %(project_id)s AND workspace_id = %(workspace_id)s",
            {"project_id": project_id, "workspace_id": workspace_id},
        )
        logger.info("Deleted project_spans for project %s", project_id)
    except Exception:
        logger.exception("Failed to delete project_spans for project %s", project_id)


def fetch_project_trace_spans(project_id: str, trace_id: str, workspace_id: str) -> list[dict]:
    """Fetch spans for a single trace from a project snapshot."""
    try:
        client = _get_client()
        rows = client.execute(
            "SELECT project_id, trace_id, span_id, parent_span_id, workspace_id, "
            "name, kind, status, start_time, end_time, model, agent_name, "
            "input_tokens, output_tokens, retry_count, error_message, attributes_json "
            "FROM project_spans "
            "WHERE project_id = %(project_id)s AND trace_id = %(trace_id)s "
            "AND workspace_id = %(workspace_id)s "
            "ORDER BY start_time",
            {"project_id": project_id, "trace_id": trace_id, "workspace_id": workspace_id},
        )
        columns = [
            "project_id", "trace_id", "span_id", "parent_span_id", "workspace_id",
            "name", "kind", "status", "start_time", "end_time",
            "model", "agent_name", "input_tokens", "output_tokens",
            "retry_count", "error_message", "attributes_json",
        ]
        return [dict(zip(columns, row)) for row in rows]
    except Exception:
        logger.exception("Failed to fetch project trace spans for project %s trace %s", project_id, trace_id)
        return []


def fetch_project_spans_stats_batch(
    project_id: str, trace_ids: list[str], workspace_id: str
) -> dict[str, dict]:
    """Return span stats for project traces keyed by trace_id: span_count, llm_calls, total_ms."""
    if not trace_ids:
        return {}
    try:
        client = _get_client()
        rows = client.execute(
            "SELECT trace_id, "
            "  count() AS span_count, "
            "  countIf(kind = 'llm_call') AS llm_calls, "
            "  dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
            "FROM project_spans "
            "WHERE project_id = %(pid)s AND workspace_id = %(ws)s AND trace_id IN %(ids)s "
            "GROUP BY trace_id",
            {"pid": project_id, "ws": workspace_id, "ids": tuple(trace_ids)},
        )
        return {
            row[0]: {"span_count": row[1], "llm_calls": row[2], "total_ms": row[3]}
            for row in rows
        }
    except Exception:
        logger.exception("Failed to fetch project span stats batch for project %s", project_id)
        return {}


def fetch_spans_by_filter(
    workspace_id: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    trace_ids: list[str] | None = None,
) -> list[dict]:
    """Fetch spans for a workspace with optional date range and trace_id filters."""
    try:
        client = _get_client()
        conditions = ["workspace_id = %(workspace_id)s"]
        params: dict = {"workspace_id": workspace_id}

        if date_from is not None:
            conditions.append("start_time >= %(date_from)s")
            params["date_from"] = date_from

        if date_to is not None:
            conditions.append("start_time <= %(date_to)s")
            params["date_to"] = date_to

        if trace_ids:
            conditions.append("trace_id IN %(trace_ids)s")
            params["trace_ids"] = tuple(trace_ids)

        where_clause = " AND ".join(conditions)
        query = (
            f"SELECT * FROM spans WHERE {where_clause} "
            "ORDER BY trace_id, start_time"
        )
        rows = client.execute(query, params)
        columns = [
            "trace_id", "span_id", "parent_span_id", "workspace_id",
            "name", "kind", "status", "start_time", "end_time",
            "model", "agent_name", "input_tokens", "output_tokens",
            "retry_count", "error_message", "attributes_json",
        ]
        return [dict(zip(columns, row)) for row in rows]
    except Exception:
        logger.exception("Failed to fetch spans by filter for workspace %s", workspace_id)
        return []
