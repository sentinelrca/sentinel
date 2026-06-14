"""SpanStore protocol — the OLAP storage contract for Sentinel.

Any class that implements these methods is a valid SpanStore backend:
  - ClickHouseSpanStore  →  self-hosted Docker / on-prem (default)
  - TinybirdSpanStore    →  hosted SaaS (Tinybird free tier)

Call sites import only from this protocol, never from a specific backend.
The backend is selected at startup via SENTINEL_STORAGE_BACKEND env var.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from sentinel_pipeline.models.span import NormalizedSpan


@runtime_checkable
class SpanStore(Protocol):
    """OLAP storage contract for raw span/trace data."""

    # ── Setup ──────────────────────────────────────────────────────────────

    def ensure_tables(self) -> None:
        """Create tables/datasources if they don't exist. Called at worker startup."""
        ...

    # ── Live spans (sync path) ─────────────────────────────────────────────

    def insert_spans(self, spans: list[NormalizedSpan]) -> None:
        """Bulk insert spans from a live sync."""
        ...

    def fetch_trace_spans(self, trace_id: str, workspace_id: str) -> list[dict]:
        """Fetch all spans for one trace. Returns list of raw dicts."""
        ...

    def count_distinct_traces(self, workspace_id: str) -> int:
        """Count distinct trace_ids for a workspace."""
        ...

    def fetch_trace_stats_batch(
        self, trace_ids: list[str], workspace_id: str
    ) -> dict[str, dict]:
        """Return {trace_id: {span_count, llm_calls, total_ms}} for a batch of traces."""
        ...

    def fetch_spans_by_filter(
        self,
        workspace_id: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        trace_ids: list[str] | None = None,
    ) -> list[dict]:
        """Fetch spans with optional date range and/or trace_id filters."""
        ...

    def delete_spans_older_than(self, workspace_id: str, cutoff_iso: str) -> None:
        """Delete live spans older than cutoff_iso. Used by retention cleanup."""
        ...

    # ── Project spans (offline analysis path) ─────────────────────────────

    def insert_project_spans(
        self, project_id: str, spans: list[NormalizedSpan]
    ) -> None:
        """Bulk insert spans into a project snapshot."""
        ...

    def fetch_project_spans(
        self, project_id: str, workspace_id: str
    ) -> list[dict]:
        """Fetch all spans for a project snapshot."""
        ...

    def fetch_project_trace_spans(
        self, project_id: str, trace_id: str, workspace_id: str
    ) -> list[dict]:
        """Fetch spans for a single trace within a project snapshot."""
        ...

    def fetch_project_spans_stats_batch(
        self, project_id: str, trace_ids: list[str], workspace_id: str
    ) -> dict[str, dict]:
        """Return span stats for project traces keyed by trace_id."""
        ...

    def delete_project_spans(self, project_id: str, workspace_id: str) -> None:
        """Delete all spans for a project. Called on project delete."""
        ...
