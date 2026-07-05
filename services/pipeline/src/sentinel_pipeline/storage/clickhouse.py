"""ClickHouse implementation of SpanStore.

Used for self-hosted deployments (Docker Compose, on-prem).
Connects via CLICKHOUSE_URL env var (default: clickhouse://localhost:9000/sentinel).
"""

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

_SPAN_COLUMNS = [
    "trace_id",
    "span_id",
    "parent_span_id",
    "workspace_id",
    "name",
    "kind",
    "status",
    "start_time",
    "end_time",
    "model",
    "agent_name",
    "input_tokens",
    "output_tokens",
    "retry_count",
    "error_message",
    "attributes_json",
]

_PROJECT_SPAN_COLUMNS = ["project_id"] + _SPAN_COLUMNS


def _get_client() -> Client:
    parsed = urlparse(_CLICKHOUSE_URL)
    return Client(
        host=parsed.hostname or "localhost",
        port=parsed.port or 9000,
        database=parsed.path.lstrip("/") or "sentinel",
        send_receive_timeout=30,
    )


def _span_row(s: NormalizedSpan) -> tuple:
    return (
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


class ClickHouseSpanStore:
    """SpanStore backed by a ClickHouse instance."""

    def ensure_tables(self) -> None:
        try:
            client = _get_client()
            client.execute(_CREATE_SPANS_TABLE)
            client.execute(_CREATE_PROJECT_SPANS_TABLE)
            logger.info("ClickHouse tables ready")
        except Exception:
            logger.exception("Failed to ensure ClickHouse tables")

    # ── Live spans ─────────────────────────────────────────────────────────

    def insert_spans(self, spans: list[NormalizedSpan]) -> None:
        if not spans:
            return
        try:
            _get_client().execute("INSERT INTO spans VALUES", [_span_row(s) for s in spans])
        except Exception:
            logger.exception("Failed to insert %d spans", len(spans))
            raise

    def fetch_trace_spans(self, trace_id: str, workspace_id: str) -> list[dict]:
        try:
            rows = _get_client().execute(
                "SELECT * FROM spans WHERE trace_id = %(trace_id)s "
                "AND workspace_id = %(workspace_id)s ORDER BY start_time",
                {"trace_id": trace_id, "workspace_id": workspace_id},
            )
            return [dict(zip(_SPAN_COLUMNS, row)) for row in rows]
        except Exception:
            logger.exception("Failed to fetch spans for trace %s", trace_id)
            return []

    def count_distinct_traces(self, workspace_id: str) -> int:
        try:
            rows = _get_client().execute(
                "SELECT count(DISTINCT trace_id) FROM spans WHERE workspace_id = %(ws)s",
                {"ws": workspace_id},
            )
            return rows[0][0] if rows else 0
        except Exception:
            logger.exception("Failed to count distinct traces for workspace %s", workspace_id)
            return 0

    def fetch_trace_stats_batch(self, trace_ids: list[str], workspace_id: str) -> dict[str, dict]:
        if not trace_ids:
            return {}
        try:
            rows = _get_client().execute(
                "SELECT trace_id, count() AS span_count, "
                "countIf(kind = 'llm_call') AS llm_calls, "
                "dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
                "FROM spans WHERE workspace_id = %(ws)s AND trace_id IN %(ids)s "
                "GROUP BY trace_id",
                {"ws": workspace_id, "ids": tuple(trace_ids)},
            )
            return {r[0]: {"span_count": r[1], "llm_calls": r[2], "total_ms": r[3]} for r in rows}
        except Exception:
            logger.exception("Failed to fetch trace stats batch")
            return {}

    def fetch_spans_by_filter(
        self,
        workspace_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        trace_ids: list[str] | None = None,
    ) -> list[dict]:
        try:
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
            rows = _get_client().execute(
                f"SELECT * FROM spans WHERE {' AND '.join(conditions)} "
                "ORDER BY trace_id, start_time",
                params,
            )
            return [dict(zip(_SPAN_COLUMNS, row)) for row in rows]
        except Exception:
            logger.exception("Failed to fetch spans by filter for workspace %s", workspace_id)
            return []

    def delete_spans_older_than(self, workspace_id: str, cutoff_iso: str) -> None:
        try:
            _get_client().execute(
                "ALTER TABLE spans DELETE WHERE workspace_id = %(ws)s AND start_time < %(cutoff)s",
                {"ws": workspace_id, "cutoff": cutoff_iso},
            )
            logger.info(
                "Queued retention cleanup for workspace %s (cutoff %s)", workspace_id, cutoff_iso
            )
        except Exception:
            logger.exception("Failed to delete old spans for workspace %s", workspace_id)
            raise

    # ── Project spans ──────────────────────────────────────────────────────

    def insert_project_spans(self, project_id: str, spans: list[NormalizedSpan]) -> None:
        if not spans:
            return
        try:
            rows = [(project_id, *_span_row(s)) for s in spans]
            _get_client().execute("INSERT INTO project_spans VALUES", rows)
        except Exception:
            logger.exception(
                "Failed to insert %d project spans for project %s", len(spans), project_id
            )
            raise

    def fetch_project_spans(self, project_id: str, workspace_id: str) -> list[dict]:
        try:
            rows = _get_client().execute(
                "SELECT project_id, trace_id, span_id, parent_span_id, workspace_id, "
                "name, kind, status, start_time, end_time, model, agent_name, "
                "input_tokens, output_tokens, retry_count, error_message, attributes_json "
                "FROM project_spans "
                "WHERE project_id = %(project_id)s AND workspace_id = %(workspace_id)s "
                "ORDER BY trace_id, start_time",
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            return [dict(zip(_PROJECT_SPAN_COLUMNS, row)) for row in rows]
        except Exception:
            logger.exception("Failed to fetch project spans for project %s", project_id)
            return []

    def fetch_project_trace_spans(
        self, project_id: str, trace_id: str, workspace_id: str
    ) -> list[dict]:
        try:
            rows = _get_client().execute(
                "SELECT project_id, trace_id, span_id, parent_span_id, workspace_id, "
                "name, kind, status, start_time, end_time, model, agent_name, "
                "input_tokens, output_tokens, retry_count, error_message, attributes_json "
                "FROM project_spans "
                "WHERE project_id = %(project_id)s AND trace_id = %(trace_id)s "
                "AND workspace_id = %(workspace_id)s ORDER BY start_time",
                {"project_id": project_id, "trace_id": trace_id, "workspace_id": workspace_id},
            )
            return [dict(zip(_PROJECT_SPAN_COLUMNS, row)) for row in rows]
        except Exception:
            logger.exception(
                "Failed to fetch project trace spans for project %s trace %s", project_id, trace_id
            )
            return []

    def fetch_project_spans_stats_batch(
        self, project_id: str, trace_ids: list[str], workspace_id: str
    ) -> dict[str, dict]:
        if not trace_ids:
            return {}
        try:
            rows = _get_client().execute(
                "SELECT trace_id, count() AS span_count, "
                "countIf(kind = 'llm_call') AS llm_calls, "
                "dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
                "FROM project_spans "
                "WHERE project_id = %(pid)s AND workspace_id = %(ws)s AND trace_id IN %(ids)s "
                "GROUP BY trace_id",
                {"pid": project_id, "ws": workspace_id, "ids": tuple(trace_ids)},
            )
            return {r[0]: {"span_count": r[1], "llm_calls": r[2], "total_ms": r[3]} for r in rows}
        except Exception:
            logger.exception("Failed to fetch project span stats batch for project %s", project_id)
            return {}

    def delete_project_spans(self, project_id: str, workspace_id: str) -> None:
        try:
            _get_client().execute(
                "ALTER TABLE project_spans DELETE "
                "WHERE project_id = %(project_id)s AND workspace_id = %(workspace_id)s",
                {"project_id": project_id, "workspace_id": workspace_id},
            )
            logger.info("Deleted project_spans for project %s", project_id)
        except Exception:
            logger.exception("Failed to delete project_spans for project %s", project_id)
