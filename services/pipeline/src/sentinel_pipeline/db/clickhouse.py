"""Backward-compatible shim — delegates to the active SpanStore backend.

Existing call sites (worker tasks, API routers) continue to import from here
without any changes. The actual implementation lives in sentinel_pipeline.storage.

To switch backends, set SENTINEL_STORAGE_BACKEND=tinybird in the environment.
Default is clickhouse (self-hosted Docker / on-prem).
"""

from __future__ import annotations

from datetime import datetime

from sentinel_pipeline.models.span import NormalizedSpan
from sentinel_pipeline.storage import get_span_store


def ensure_tables() -> None:
    get_span_store().ensure_tables()


def insert_spans(spans: list[NormalizedSpan]) -> None:
    get_span_store().insert_spans(spans)


def fetch_trace_spans(trace_id: str, workspace_id: str) -> list[dict]:
    return get_span_store().fetch_trace_spans(trace_id, workspace_id)


def count_distinct_traces(workspace_id: str) -> int:
    return get_span_store().count_distinct_traces(workspace_id)


def fetch_trace_stats_batch(trace_ids: list[str], workspace_id: str) -> dict[str, dict]:
    return get_span_store().fetch_trace_stats_batch(trace_ids, workspace_id)


def fetch_spans_by_filter(
    workspace_id: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    trace_ids: list[str] | None = None,
) -> list[dict]:
    return get_span_store().fetch_spans_by_filter(workspace_id, date_from, date_to, trace_ids)


def delete_spans_older_than(workspace_id: str, cutoff_iso: str) -> None:
    get_span_store().delete_spans_older_than(workspace_id, cutoff_iso)


def insert_project_spans(project_id: str, spans: list[NormalizedSpan]) -> None:
    get_span_store().insert_project_spans(project_id, spans)


def fetch_project_spans(project_id: str, workspace_id: str) -> list[dict]:
    return get_span_store().fetch_project_spans(project_id, workspace_id)


def fetch_project_trace_spans(project_id: str, trace_id: str, workspace_id: str) -> list[dict]:
    return get_span_store().fetch_project_trace_spans(project_id, trace_id, workspace_id)


def fetch_project_spans_stats_batch(
    project_id: str, trace_ids: list[str], workspace_id: str
) -> dict[str, dict]:
    return get_span_store().fetch_project_spans_stats_batch(project_id, trace_ids, workspace_id)


def delete_project_spans(project_id: str, workspace_id: str) -> None:
    get_span_store().delete_project_spans(project_id, workspace_id)
