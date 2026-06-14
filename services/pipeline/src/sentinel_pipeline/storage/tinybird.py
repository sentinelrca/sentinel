"""Tinybird implementation of SpanStore.

Used for hosted SaaS deployments. Connects via:
  TINYBIRD_API_KEY  — token from Tinybird workspace
  TINYBIRD_HOST     — defaults to https://api.tinybird.co (US region)
                      use https://api.eu-central-1.tinybird.co for EU

Ingestion:  Tinybird Events API  (POST /v0/events)
Queries:    Tinybird SQL API     (POST /v0/sql)

Tinybird datasources must exist before use. Create them once via:
  tb datasource create --schema infra/tinybird/spans.datasource
  tb datasource create --schema infra/tinybird/project_spans.datasource
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

import httpx

from sentinel_pipeline.models.span import NormalizedSpan

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "https://api.tinybird.co"
_SPANS_DS      = "spans"
_PROJECT_DS    = "project_spans"

# Allowlist for values interpolated into SQL — prevents injection.
# IDs from Sentinel are UUIDs (hex + dashes) or short alphanumeric strings.
_SAFE_ID_RE = re.compile(r"^[0-9a-fA-F\-]{1,128}$")


def _safe_id(value: str, name: str) -> str:
    """Validate that an ID value is safe to interpolate into SQL.
    Raises ValueError if it contains characters outside the allowlist.
    """
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"Unsafe value for SQL parameter '{name}': {value!r}")
    return value


def _dt_to_sql(dt: datetime) -> str:
    """Format a datetime for Tinybird/ClickHouse DateTime — UTC, second precision."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _dt_to_ingest(dt: datetime) -> str:
    """Format a datetime for Tinybird ingest — ISO 8601 with millisecond precision."""
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{utc.microsecond // 1000:03d}Z"


def _span_to_ndjson(s: NormalizedSpan) -> dict:
    return {
        "trace_id":        s.trace_id,
        "span_id":         s.span_id,
        "parent_span_id":  s.parent_span_id or "",
        "workspace_id":    s.workspace_id,
        "name":            s.name,
        "kind":            s.kind.value,
        "status":          s.status.value,
        "start_time":      _dt_to_ingest(s.start_time),
        "end_time":        _dt_to_ingest(s.end_time),
        "model":           s.model or "",
        "agent_name":      s.agent_name or "",
        "input_tokens":    s.input_tokens or 0,
        "output_tokens":   s.output_tokens or 0,
        "retry_count":     s.retry_count,
        "error_message":   s.error_message or "",
        "attributes_json": json.dumps(s.attributes),
    }


class TinybirdSpanStore:
    """SpanStore backed by Tinybird (hosted SaaS, free tier available)."""

    def __init__(self) -> None:
        self._api_key = os.environ.get("TINYBIRD_API_KEY", "")
        self._host    = os.environ.get("TINYBIRD_HOST", _DEFAULT_HOST).rstrip("/")
        if not self._api_key:
            raise RuntimeError(
                "TINYBIRD_API_KEY is not set. "
                "Get your token from app.tinybird.co → Auth Tokens."
            )

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _ingest(self, datasource: str, rows: list[dict]) -> None:
        """POST rows to Tinybird Events API as NDJSON."""
        ndjson = "\n".join(json.dumps(r) for r in rows)
        resp = httpx.post(
            f"{self._host}/v0/events",
            params={"name": datasource},
            content=ndjson.encode(),
            headers={**self._headers(), "Content-Type": "application/x-ndjson"},
            timeout=30,
        )
        resp.raise_for_status()

    def _query(self, sql: str) -> list[dict]:
        """Run SQL against Tinybird SQL API, return list of row dicts."""
        resp = httpx.post(
            f"{self._host}/v0/sql",
            data={"q": sql + " FORMAT JSON"},
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    def _delete(self, datasource: str, condition: str) -> None:
        """Delete rows using Tinybird's delete-by-condition endpoint."""
        resp = httpx.delete(
            f"{self._host}/v0/datasources/{datasource}/rows",
            params={"delete_condition": condition},   # Tinybird requires 'delete_condition'
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()

    # ── Setup ──────────────────────────────────────────────────────────────

    def ensure_tables(self) -> None:
        """Tinybird datasources are created via CLI/UI — this is a no-op."""
        logger.info(
            "Tinybird: datasources must be created manually. "
            "See infra/tinybird/ for schema files."
        )

    # ── Live spans ─────────────────────────────────────────────────────────

    def insert_spans(self, spans: list[NormalizedSpan]) -> None:
        if not spans:
            return
        try:
            self._ingest(_SPANS_DS, [_span_to_ndjson(s) for s in spans])
        except Exception:
            logger.exception("Tinybird: failed to insert %d spans", len(spans))
            raise

    def fetch_trace_spans(self, trace_id: str, workspace_id: str) -> list[dict]:
        tid = _safe_id(trace_id, "trace_id")        # validate before try — injection must not be swallowed
        wid = _safe_id(workspace_id, "workspace_id")
        try:
            return self._query(
                f"SELECT * FROM {_SPANS_DS} "
                f"WHERE trace_id = '{tid}' AND workspace_id = '{wid}' "
                f"ORDER BY start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch spans for trace %s", trace_id)
            return []

    def count_distinct_traces(self, workspace_id: str) -> int:
        wid = _safe_id(workspace_id, "workspace_id")
        try:
            rows = self._query(
                f"SELECT count(DISTINCT trace_id) AS n FROM {_SPANS_DS} "
                f"WHERE workspace_id = '{wid}'"
            )
            return int(rows[0]["n"]) if rows else 0
        except Exception:
            logger.exception("Tinybird: failed to count traces for workspace %s", workspace_id)
            return 0

    def fetch_trace_stats_batch(
        self, trace_ids: list[str], workspace_id: str
    ) -> dict[str, dict]:
        if not trace_ids:
            return {}
        wid      = _safe_id(workspace_id, "workspace_id")
        ids_list = ", ".join(f"'{_safe_id(t, 'trace_id')}'" for t in trace_ids)
        try:
            rows = self._query(
                f"SELECT trace_id, count() AS span_count, "
                f"countIf(kind = 'llm_call') AS llm_calls, "
                f"dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
                f"FROM {_SPANS_DS} "
                f"WHERE workspace_id = '{wid}' AND trace_id IN ({ids_list}) "
                f"GROUP BY trace_id"
            )
            return {
                r["trace_id"]: {
                    "span_count": r["span_count"],
                    "llm_calls":  r["llm_calls"],
                    "total_ms":   r["total_ms"],
                }
                for r in rows
            }
        except Exception:
            logger.exception("Tinybird: failed to fetch trace stats batch")
            return {}

    def fetch_spans_by_filter(
        self,
        workspace_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        trace_ids: list[str] | None = None,
    ) -> list[dict]:
        wid = _safe_id(workspace_id, "workspace_id")
        try:
            conditions = [f"workspace_id = '{wid}'"]
            if date_from:
                conditions.append(f"start_time >= '{_dt_to_sql(date_from)}'")
            if date_to:
                conditions.append(f"start_time <= '{_dt_to_sql(date_to)}'")
            if trace_ids:
                ids_list = ", ".join(f"'{_safe_id(t, 'trace_id')}'" for t in trace_ids)
                conditions.append(f"trace_id IN ({ids_list})")
            where = " AND ".join(conditions)
            return self._query(
                f"SELECT * FROM {_SPANS_DS} WHERE {where} ORDER BY trace_id, start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch spans by filter for workspace %s", workspace_id)
            return []

    def delete_spans_older_than(self, workspace_id: str, cutoff_iso: str) -> None:
        wid = _safe_id(workspace_id, "workspace_id")
        try:
            # cutoff_iso comes from _dt_to_sql() in the caller — already UTC, safe format
            self._delete(
                _SPANS_DS,
                f"workspace_id = '{wid}' AND start_time < '{cutoff_iso}'",
            )
            logger.info("Tinybird: queued retention cleanup for workspace %s", workspace_id)
        except Exception:
            logger.exception("Tinybird: failed to delete old spans for workspace %s", workspace_id)
            raise

    # ── Project spans ──────────────────────────────────────────────────────

    def insert_project_spans(self, project_id: str, spans: list[NormalizedSpan]) -> None:
        if not spans:
            return
        try:
            rows = [{"project_id": project_id, **_span_to_ndjson(s)} for s in spans]
            self._ingest(_PROJECT_DS, rows)
        except Exception:
            logger.exception("Tinybird: failed to insert %d project spans for project %s", len(spans), project_id)
            raise

    def fetch_project_spans(self, project_id: str, workspace_id: str) -> list[dict]:
        pid = _safe_id(project_id, "project_id")
        wid = _safe_id(workspace_id, "workspace_id")
        try:
            return self._query(
                f"SELECT * FROM {_PROJECT_DS} "
                f"WHERE project_id = '{pid}' AND workspace_id = '{wid}' "
                f"ORDER BY trace_id, start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch project spans for project %s", project_id)
            return []

    def fetch_project_trace_spans(
        self, project_id: str, trace_id: str, workspace_id: str
    ) -> list[dict]:
        pid = _safe_id(project_id, "project_id")
        tid = _safe_id(trace_id, "trace_id")
        wid = _safe_id(workspace_id, "workspace_id")
        try:
            return self._query(
                f"SELECT * FROM {_PROJECT_DS} "
                f"WHERE project_id = '{pid}' AND trace_id = '{tid}' "
                f"AND workspace_id = '{wid}' ORDER BY start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch project trace spans for project %s trace %s", project_id, trace_id)
            return []

    def fetch_project_spans_stats_batch(
        self, project_id: str, trace_ids: list[str], workspace_id: str
    ) -> dict[str, dict]:
        if not trace_ids:
            return {}
        pid      = _safe_id(project_id, "project_id")
        wid      = _safe_id(workspace_id, "workspace_id")
        ids_list = ", ".join(f"'{_safe_id(t, 'trace_id')}'" for t in trace_ids)
        try:
            rows = self._query(
                f"SELECT trace_id, count() AS span_count, "
                f"countIf(kind = 'llm_call') AS llm_calls, "
                f"dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
                f"FROM {_PROJECT_DS} "
                f"WHERE project_id = '{pid}' AND workspace_id = '{wid}' "
                f"AND trace_id IN ({ids_list}) GROUP BY trace_id"
            )
            return {
                r["trace_id"]: {
                    "span_count": r["span_count"],
                    "llm_calls":  r["llm_calls"],
                    "total_ms":   r["total_ms"],
                }
                for r in rows
            }
        except Exception:
            logger.exception("Tinybird: failed to fetch project span stats for project %s", project_id)
            return {}

    def delete_project_spans(self, project_id: str, workspace_id: str) -> None:
        pid = _safe_id(project_id, "project_id")
        wid = _safe_id(workspace_id, "workspace_id")
        try:
            self._delete(
                _PROJECT_DS,
                f"project_id = '{pid}' AND workspace_id = '{wid}'",
            )
            logger.info("Tinybird: deleted project_spans for project %s", project_id)
        except Exception:
            logger.exception("Tinybird: failed to delete project_spans for project %s", project_id)
