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
from datetime import datetime

import httpx

from sentinel_pipeline.models.span import NormalizedSpan

logger = logging.getLogger(__name__)

_DEFAULT_HOST = "https://api.tinybird.co"
_SPANS_DS      = "spans"
_PROJECT_DS    = "project_spans"

_SPAN_COLUMNS = [
    "trace_id", "span_id", "parent_span_id", "workspace_id",
    "name", "kind", "status", "start_time", "end_time",
    "model", "agent_name", "input_tokens", "output_tokens",
    "retry_count", "error_message", "attributes_json",
]
_PROJECT_SPAN_COLUMNS = ["project_id"] + _SPAN_COLUMNS


def _span_to_ndjson(s: NormalizedSpan) -> dict:
    return {
        "trace_id":       s.trace_id,
        "span_id":        s.span_id,
        "parent_span_id": s.parent_span_id or "",
        "workspace_id":   s.workspace_id,
        "name":           s.name,
        "kind":           s.kind.value,
        "status":         s.status.value,
        "start_time":     s.start_time.isoformat(),
        "end_time":       s.end_time.isoformat(),
        "model":          s.model or "",
        "agent_name":     s.agent_name or "",
        "input_tokens":   s.input_tokens or 0,
        "output_tokens":  s.output_tokens or 0,
        "retry_count":    s.retry_count,
        "error_message":  s.error_message or "",
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
        """Delete rows using Tinybird's delete by condition endpoint."""
        resp = httpx.delete(
            f"{self._host}/v0/datasources/{datasource}/rows",
            params={"condition": condition},
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
        try:
            return self._query(
                f"SELECT * FROM {_SPANS_DS} "
                f"WHERE trace_id = '{trace_id}' AND workspace_id = '{workspace_id}' "
                f"ORDER BY start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch spans for trace %s", trace_id)
            return []

    def count_distinct_traces(self, workspace_id: str) -> int:
        try:
            rows = self._query(
                f"SELECT count(DISTINCT trace_id) AS n FROM {_SPANS_DS} "
                f"WHERE workspace_id = '{workspace_id}'"
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
        try:
            ids_list = ", ".join(f"'{t}'" for t in trace_ids)
            rows = self._query(
                f"SELECT trace_id, count() AS span_count, "
                f"countIf(kind = 'llm_call') AS llm_calls, "
                f"dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
                f"FROM {_SPANS_DS} "
                f"WHERE workspace_id = '{workspace_id}' AND trace_id IN ({ids_list}) "
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
        try:
            conditions = [f"workspace_id = '{workspace_id}'"]
            if date_from:
                conditions.append(f"start_time >= '{date_from.isoformat()}'")
            if date_to:
                conditions.append(f"start_time <= '{date_to.isoformat()}'")
            if trace_ids:
                ids_list = ", ".join(f"'{t}'" for t in trace_ids)
                conditions.append(f"trace_id IN ({ids_list})")
            where = " AND ".join(conditions)
            return self._query(
                f"SELECT * FROM {_SPANS_DS} WHERE {where} ORDER BY trace_id, start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch spans by filter for workspace %s", workspace_id)
            return []

    def delete_spans_older_than(self, workspace_id: str, cutoff_iso: str) -> None:
        try:
            self._delete(
                _SPANS_DS,
                f"workspace_id = '{workspace_id}' AND start_time < '{cutoff_iso}'",
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
        try:
            return self._query(
                f"SELECT * FROM {_PROJECT_DS} "
                f"WHERE project_id = '{project_id}' AND workspace_id = '{workspace_id}' "
                f"ORDER BY trace_id, start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch project spans for project %s", project_id)
            return []

    def fetch_project_trace_spans(
        self, project_id: str, trace_id: str, workspace_id: str
    ) -> list[dict]:
        try:
            return self._query(
                f"SELECT * FROM {_PROJECT_DS} "
                f"WHERE project_id = '{project_id}' AND trace_id = '{trace_id}' "
                f"AND workspace_id = '{workspace_id}' ORDER BY start_time"
            )
        except Exception:
            logger.exception("Tinybird: failed to fetch project trace spans for project %s trace %s", project_id, trace_id)
            return []

    def fetch_project_spans_stats_batch(
        self, project_id: str, trace_ids: list[str], workspace_id: str
    ) -> dict[str, dict]:
        if not trace_ids:
            return {}
        try:
            ids_list = ", ".join(f"'{t}'" for t in trace_ids)
            rows = self._query(
                f"SELECT trace_id, count() AS span_count, "
                f"countIf(kind = 'llm_call') AS llm_calls, "
                f"dateDiff('millisecond', min(start_time), max(end_time)) AS total_ms "
                f"FROM {_PROJECT_DS} "
                f"WHERE project_id = '{project_id}' AND workspace_id = '{workspace_id}' "
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
        try:
            self._delete(
                _PROJECT_DS,
                f"project_id = '{project_id}' AND workspace_id = '{workspace_id}'",
            )
            logger.info("Tinybird: deleted project_spans for project %s", project_id)
        except Exception:
            logger.exception("Tinybird: failed to delete project_spans for project %s", project_id)
