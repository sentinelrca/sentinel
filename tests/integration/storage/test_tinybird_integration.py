"""
Integration tests for TinybirdSpanStore against a real Tinybird workspace.

Requires env vars (skip automatically if absent):
  TINYBIRD_API_KEY  — Tinybird auth token
  TINYBIRD_HOST     — optional, defaults to https://api.tinybird.co

Local Docker (no account needed):
  docker run --platform linux/amd64 -p 7181:7181 --name tinybird-local \
    -e COMPATIBILITY_MODE=1 -d tinybirdco/tinybird-local:latest
  TOKEN=$(curl -s http://localhost:7181/tokens | python3 -c \
    "import sys,json; print(json.load(sys.stdin)['workspace_admin_token'])")
  # Datasources are auto-created on first Events API ingest — no tb push needed.
  TINYBIRD_API_KEY=$TOKEN TINYBIRD_HOST=http://localhost:7181 \
    uv run --no-project pytest integration/storage/test_tinybird_integration.py -v

Tinybird Cloud:
  # Sign up at app.tinybird.co (free tier, no credit card)
  # Create datasources once:
  uv tool install tinybird-cli
  tb auth --token $TINYBIRD_API_KEY
  tb push infra/tinybird/spans.datasource
  tb push infra/tinybird/project_spans.datasource
  TINYBIRD_API_KEY=... uv run --no-project pytest integration/storage/test_tinybird_integration.py -v
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.storage.tinybird import TinybirdSpanStore, _dt_to_sql


# ---------------------------------------------------------------------------
# Skip if not configured
# ---------------------------------------------------------------------------

def _get_store() -> TinybirdSpanStore:
    api_key = os.environ.get("TINYBIRD_API_KEY", "")
    if not api_key:
        pytest.skip("TINYBIRD_API_KEY not set — skipping Tinybird integration tests")
    return TinybirdSpanStore()


def _check_datasources(store: TinybirdSpanStore) -> None:
    """Verify the required datasources exist — skip with clear message if not."""
    try:
        store._query("SELECT 1 FROM spans LIMIT 1")
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 400):
            pytest.skip(
                "Tinybird 'spans' datasource not found. "
                "Create it with: tb push infra/tinybird/spans.datasource"
            )
        raise
    try:
        store._query("SELECT 1 FROM project_spans LIMIT 1")
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (404, 400):
            pytest.skip(
                "Tinybird 'project_spans' datasource not found. "
                "Create it with: tb push infra/tinybird/project_spans.datasource"
            )
        raise


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_ws() -> str:
    """Generate a unique workspace_id for test isolation (UUID hex, no dashes — within allowlist)."""
    return uuid.uuid4().hex   # 32-char hex, safe for _safe_id


def _span(
    trace_id: str,
    span_id: str,
    workspace_id: str,
    kind: SpanKind = SpanKind.LLM_CALL,
    model: str | None = "gpt-4o-mini",
    input_tokens: int = 100,
    output_tokens: int = 50,
    offset_seconds: int = 0,
) -> NormalizedSpan:
    t0 = datetime(2026, 1, 1, 12, 0, offset_seconds, tzinfo=timezone.utc)
    return NormalizedSpan(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=None,
        name=f"test-{kind.value}",
        kind=kind,
        status=SpanStatus.OK,
        start_time=t0,
        end_time=t0.replace(second=offset_seconds + 1),
        workspace_id=workspace_id,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _wait_for_ingestion(seconds: int = 3) -> None:
    """Tinybird Events API ingestion is asynchronous — wait briefly before querying."""
    time.sleep(seconds)


def _cleanup(store: TinybirdSpanStore, workspace_id: str) -> None:
    """Best-effort cleanup of test data after each test."""
    try:
        cutoff = _dt_to_sql(datetime(2030, 1, 1, tzinfo=timezone.utc))
        store.delete_spans_older_than(workspace_id, cutoff)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tests — live spans
# ---------------------------------------------------------------------------

def test_insert_and_fetch_spans():
    """Insert a span and retrieve it by trace_id."""
    store = _get_store()
    _check_datasources(store)

    ws       = _unique_ws()
    trace_id = uuid.uuid4().hex
    span_id  = uuid.uuid4().hex[:16]

    store.insert_spans([_span(trace_id, span_id, ws)])
    _wait_for_ingestion()

    rows = store.fetch_trace_spans(trace_id, ws)
    span_ids = [r["span_id"] for r in rows]
    assert span_id in span_ids, f"Inserted span {span_id} not found. Got: {span_ids}"

    _cleanup(store, ws)


def test_insert_multiple_spans_same_trace():
    """Multiple spans in the same trace are all retrievable."""
    store = _get_store()
    _check_datasources(store)

    ws       = _unique_ws()
    trace_id = uuid.uuid4().hex
    span_ids = [uuid.uuid4().hex[:16] for _ in range(3)]

    spans = [
        _span(trace_id, sid, ws, offset_seconds=i)
        for i, sid in enumerate(span_ids)
    ]
    store.insert_spans(spans)
    _wait_for_ingestion()

    rows = store.fetch_trace_spans(trace_id, ws)
    returned = {r["span_id"] for r in rows}
    for sid in span_ids:
        assert sid in returned, f"Span {sid} missing from fetch result"

    _cleanup(store, ws)


def test_count_distinct_traces():
    """count_distinct_traces returns the correct number of unique traces."""
    store = _get_store()
    _check_datasources(store)

    ws  = _unique_ws()
    t1  = uuid.uuid4().hex
    t2  = uuid.uuid4().hex

    store.insert_spans([
        _span(t1, uuid.uuid4().hex[:16], ws),
        _span(t1, uuid.uuid4().hex[:16], ws),   # same trace, different span
        _span(t2, uuid.uuid4().hex[:16], ws),
    ])
    _wait_for_ingestion()

    count = store.count_distinct_traces(ws)
    assert count >= 2, f"Expected >= 2 distinct traces, got {count}"

    _cleanup(store, ws)


def test_fetch_trace_stats_batch():
    """Stats batch returns span_count and llm_calls for each trace."""
    store = _get_store()
    _check_datasources(store)

    ws       = _unique_ws()
    trace_id = uuid.uuid4().hex

    store.insert_spans([
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.LLM_CALL,    offset_seconds=0),
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.LLM_CALL,    offset_seconds=1),
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.TOOL_INVOKE, offset_seconds=2),
    ])
    _wait_for_ingestion()

    stats = store.fetch_trace_stats_batch([trace_id], ws)
    assert trace_id in stats, f"trace_id {trace_id} missing from stats"
    s = stats[trace_id]
    assert s["span_count"] == 3
    assert s["llm_calls"]  == 2
    assert s["total_ms"]   >= 0

    _cleanup(store, ws)


def test_fetch_spans_by_filter_time_range():
    """fetch_spans_by_filter with date_from/date_to returns only matching spans."""
    store = _get_store()
    _check_datasources(store)

    ws        = _unique_ws()
    trace_id  = uuid.uuid4().hex
    span_in   = uuid.uuid4().hex[:16]   # inside window
    span_out  = uuid.uuid4().hex[:16]   # before window (far in the past)

    t_in  = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t_out = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    store.insert_spans([
        NormalizedSpan(span_id=span_in,  trace_id=trace_id, parent_span_id=None,
                       name="in-window",  kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_in,  end_time=t_in.replace(second=1),
                       workspace_id=ws),
        NormalizedSpan(span_id=span_out, trace_id=trace_id, parent_span_id=None,
                       name="out-window", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_out, end_time=t_out.replace(second=1),
                       workspace_id=ws),
    ])
    _wait_for_ingestion()

    since  = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    until  = datetime(2026, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
    rows   = store.fetch_spans_by_filter(ws, date_from=since, date_to=until)
    ids    = {r["span_id"] for r in rows}

    assert span_in  in ids, f"span_in {span_in} should be in window"
    assert span_out not in ids, f"span_out {span_out} should be outside window"

    _cleanup(store, ws)


def test_delete_spans_older_than():
    """delete_spans_older_than removes old spans, keeps recent ones."""
    store = _get_store()
    _check_datasources(store)

    ws       = _unique_ws()
    trace_id = uuid.uuid4().hex
    old_sid  = uuid.uuid4().hex[:16]
    new_sid  = uuid.uuid4().hex[:16]

    t_old = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t_new = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)

    store.insert_spans([
        NormalizedSpan(span_id=old_sid, trace_id=trace_id, parent_span_id=None,
                       name="old", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_old, end_time=t_old.replace(minute=1),
                       workspace_id=ws),
        NormalizedSpan(span_id=new_sid, trace_id=trace_id, parent_span_id=None,
                       name="new", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_new, end_time=t_new.replace(minute=1),
                       workspace_id=ws),
    ])
    _wait_for_ingestion()

    cutoff = _dt_to_sql(datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    store.delete_spans_older_than(ws, cutoff)
    _wait_for_ingestion(5)   # mutations are async — wait a bit longer

    rows = store.fetch_trace_spans(trace_id, ws)
    ids  = {r["span_id"] for r in rows}
    assert old_sid not in ids, f"old span {old_sid} should have been deleted"
    assert new_sid in ids,     f"new span {new_sid} should still exist"

    _cleanup(store, ws)


# ---------------------------------------------------------------------------
# Tests — project spans
# ---------------------------------------------------------------------------

def test_insert_and_fetch_project_spans():
    """Insert project spans and retrieve them."""
    store    = _get_store()
    _check_datasources(store)

    ws       = _unique_ws()
    proj_id  = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    span_id  = uuid.uuid4().hex[:16]

    store.insert_project_spans(proj_id, [_span(trace_id, span_id, ws)])
    _wait_for_ingestion()

    rows = store.fetch_project_spans(proj_id, ws)
    assert any(r["span_id"] == span_id for r in rows), \
        f"Inserted project span {span_id} not found"

    # Cleanup
    try:
        store.delete_project_spans(proj_id, ws)
    except Exception:
        pass


def test_project_spans_isolated_by_project_id():
    """Project spans from different projects don't bleed into each other."""
    store   = _get_store()
    _check_datasources(store)

    ws      = _unique_ws()
    proj_a  = uuid.uuid4().hex
    proj_b  = uuid.uuid4().hex
    trace_a = uuid.uuid4().hex
    trace_b = uuid.uuid4().hex
    sid_a   = uuid.uuid4().hex[:16]
    sid_b   = uuid.uuid4().hex[:16]

    store.insert_project_spans(proj_a, [_span(trace_a, sid_a, ws)])
    store.insert_project_spans(proj_b, [_span(trace_b, sid_b, ws)])
    _wait_for_ingestion()

    rows_a = store.fetch_project_spans(proj_a, ws)
    rows_b = store.fetch_project_spans(proj_b, ws)

    assert any(r["span_id"] == sid_a for r in rows_a)
    assert not any(r["span_id"] == sid_b for r in rows_a), \
        "Project B span leaked into Project A results"

    for p in [proj_a, proj_b]:
        try:
            store.delete_project_spans(p, ws)
        except Exception:
            pass


def test_delete_project_spans():
    """delete_project_spans removes all spans for a project."""
    store    = _get_store()
    _check_datasources(store)

    ws       = _unique_ws()
    proj_id  = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    span_ids = [uuid.uuid4().hex[:16] for _ in range(3)]

    store.insert_project_spans(proj_id, [
        _span(trace_id, sid, ws) for sid in span_ids
    ])
    _wait_for_ingestion()

    store.delete_project_spans(proj_id, ws)
    _wait_for_ingestion(5)

    rows = store.fetch_project_spans(proj_id, ws)
    assert len(rows) == 0, f"Expected 0 rows after delete, got {len(rows)}"
