"""
Integration tests for ClickHouseSpanStore against a real ClickHouse instance.

Requires running infrastructure (skip automatically if absent):
  task up   # starts ClickHouse on localhost:9000

Run:
  cd tests
  uv run --no-project pytest integration/storage/test_clickhouse_integration.py -v

Or with a custom ClickHouse URL:
  CLICKHOUSE_URL=clickhouse://user:pass@host:9000/db \
    uv run --no-project pytest integration/storage/test_clickhouse_integration.py -v
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from clickhouse_driver import Client
from urllib.parse import urlparse

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.storage.clickhouse import ClickHouseSpanStore

_CLICKHOUSE_URL = os.environ.get("CLICKHOUSE_URL", "clickhouse://localhost:9000/sentinel")


# ---------------------------------------------------------------------------
# Skip if ClickHouse is not reachable
# ---------------------------------------------------------------------------

def _get_store() -> ClickHouseSpanStore:
    parsed = urlparse(_CLICKHOUSE_URL)
    try:
        client = Client(
            host=parsed.hostname or "localhost",
            port=parsed.port or 9000,
            database=parsed.path.lstrip("/") or "sentinel",
            send_receive_timeout=5,
        )
        client.execute("SELECT 1")
    except Exception:
        pytest.skip("ClickHouse not reachable — run 'task up' and retry")
    store = ClickHouseSpanStore()
    store.ensure_tables()
    return store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws() -> str:
    return uuid.uuid4().hex


def _span(
    trace_id: str,
    span_id: str,
    workspace_id: str,
    kind: SpanKind = SpanKind.LLM_CALL,
    offset_seconds: int = 0,
) -> NormalizedSpan:
    t0 = datetime(2026, 1, 1, 12, 0, offset_seconds, tzinfo=timezone.utc)
    return NormalizedSpan(
        span_id=span_id, trace_id=trace_id, parent_span_id=None,
        name=f"test-{kind.value}", kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0.replace(second=offset_seconds + 1),
        workspace_id=workspace_id, model="gpt-4o-mini",
        input_tokens=100, output_tokens=50,
    )


def _cleanup(store: ClickHouseSpanStore, workspace_id: str) -> None:
    try:
        store.delete_spans_older_than(workspace_id, "2030-01-01T00:00:00")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Tests — live spans
# ---------------------------------------------------------------------------

def test_ensure_tables_is_idempotent():
    """ensure_tables can be called multiple times without error."""
    store = _get_store()
    store.ensure_tables()   # second call should be a no-op


def test_insert_and_fetch_spans():
    store    = _get_store()
    ws       = _ws()
    trace_id = uuid.uuid4().hex
    span_id  = uuid.uuid4().hex[:16]

    store.insert_spans([_span(trace_id, span_id, ws)])
    rows = store.fetch_trace_spans(trace_id, ws)

    assert any(r["span_id"] == span_id for r in rows), \
        f"Span {span_id} not found in {[r['span_id'] for r in rows]}"
    _cleanup(store, ws)


def test_insert_empty_spans_is_noop():
    store = _get_store()
    store.insert_spans([])   # must not raise


def test_insert_multiple_spans_same_trace():
    store    = _get_store()
    ws       = _ws()
    trace_id = uuid.uuid4().hex
    span_ids = [uuid.uuid4().hex[:16] for _ in range(3)]

    store.insert_spans([_span(trace_id, sid, ws, offset_seconds=i) for i, sid in enumerate(span_ids)])
    rows     = store.fetch_trace_spans(trace_id, ws)
    returned = {r["span_id"] for r in rows}
    for sid in span_ids:
        assert sid in returned
    _cleanup(store, ws)


def test_count_distinct_traces():
    store = _get_store()
    ws    = _ws()
    t1    = uuid.uuid4().hex
    t2    = uuid.uuid4().hex

    store.insert_spans([
        _span(t1, uuid.uuid4().hex[:16], ws),
        _span(t1, uuid.uuid4().hex[:16], ws),
        _span(t2, uuid.uuid4().hex[:16], ws),
    ])
    count = store.count_distinct_traces(ws)
    assert count == 2, f"Expected exactly 2 distinct traces, got {count}"
    _cleanup(store, ws)


def test_fetch_trace_stats_batch():
    store    = _get_store()
    ws       = _ws()
    trace_id = uuid.uuid4().hex

    store.insert_spans([
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.LLM_CALL,    offset_seconds=0),
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.LLM_CALL,    offset_seconds=1),
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.TOOL_INVOKE, offset_seconds=2),
    ])
    stats = store.fetch_trace_stats_batch([trace_id], ws)
    assert trace_id in stats
    s = stats[trace_id]
    assert s["span_count"] == 3
    assert s["llm_calls"]  == 2
    assert s["total_ms"]   >= 0
    _cleanup(store, ws)


def test_fetch_trace_stats_batch_empty_returns_empty():
    store = _get_store()
    assert store.fetch_trace_stats_batch([], "ws-x") == {}


def test_fetch_spans_by_filter_time_range():
    store     = _get_store()
    ws        = _ws()
    trace_id  = uuid.uuid4().hex
    sid_in    = uuid.uuid4().hex[:16]
    sid_out   = uuid.uuid4().hex[:16]

    t_in  = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    t_out = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    store.insert_spans([
        NormalizedSpan(span_id=sid_in,  trace_id=trace_id, parent_span_id=None,
                       name="in",  kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_in,  end_time=t_in.replace(second=1),  workspace_id=ws),
        NormalizedSpan(span_id=sid_out, trace_id=trace_id, parent_span_id=None,
                       name="out", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_out, end_time=t_out.replace(second=1), workspace_id=ws),
    ])

    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    until = datetime(2026, 12, 31, tzinfo=timezone.utc)
    rows  = store.fetch_spans_by_filter(ws, date_from=since, date_to=until)
    ids   = {r["span_id"] for r in rows}
    assert sid_in  in ids
    assert sid_out not in ids
    _cleanup(store, ws)


def test_fetch_spans_by_filter_trace_ids():
    store    = _get_store()
    ws       = _ws()
    t1       = uuid.uuid4().hex
    t2       = uuid.uuid4().hex
    sid1     = uuid.uuid4().hex[:16]
    sid2     = uuid.uuid4().hex[:16]

    store.insert_spans([_span(t1, sid1, ws), _span(t2, sid2, ws)])
    rows = store.fetch_spans_by_filter(ws, trace_ids=[t1])
    ids  = {r["span_id"] for r in rows}
    assert sid1 in ids
    assert sid2 not in ids
    _cleanup(store, ws)


def test_delete_spans_older_than():
    store    = _get_store()
    ws       = _ws()
    trace_id = uuid.uuid4().hex
    sid_old  = uuid.uuid4().hex[:16]
    sid_new  = uuid.uuid4().hex[:16]

    t_old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t_new = datetime(2026, 6, 1, tzinfo=timezone.utc)

    store.insert_spans([
        NormalizedSpan(span_id=sid_old, trace_id=trace_id, parent_span_id=None,
                       name="old", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_old, end_time=t_old.replace(minute=1), workspace_id=ws),
        NormalizedSpan(span_id=sid_new, trace_id=trace_id, parent_span_id=None,
                       name="new", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
                       start_time=t_new, end_time=t_new.replace(minute=1), workspace_id=ws),
    ])

    store.delete_spans_older_than(ws, "2025-01-01T00:00:00")

    # ClickHouse mutations are async — poll briefly
    import time
    for _ in range(10):
        rows = store.fetch_trace_spans(trace_id, ws)
        ids  = {r["span_id"] for r in rows}
        if sid_old not in ids:
            break
        time.sleep(1)

    rows = store.fetch_trace_spans(trace_id, ws)
    ids  = {r["span_id"] for r in rows}
    assert sid_old not in ids, f"old span should be deleted"
    assert sid_new in ids,     f"new span should remain"
    _cleanup(store, ws)


# ---------------------------------------------------------------------------
# Tests — project spans
# ---------------------------------------------------------------------------

def test_insert_and_fetch_project_spans():
    store    = _get_store()
    ws       = _ws()
    proj_id  = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    span_id  = uuid.uuid4().hex[:16]

    store.insert_project_spans(proj_id, [_span(trace_id, span_id, ws)])
    rows = store.fetch_project_spans(proj_id, ws)
    assert any(r["span_id"] == span_id for r in rows)
    store.delete_project_spans(proj_id, ws)


def test_insert_project_spans_empty_is_noop():
    store = _get_store()
    store.insert_project_spans("proj-x", [])   # must not raise


def test_project_spans_isolated_by_project_id():
    store   = _get_store()
    ws      = _ws()
    proj_a  = uuid.uuid4().hex
    proj_b  = uuid.uuid4().hex
    sid_a   = uuid.uuid4().hex[:16]
    sid_b   = uuid.uuid4().hex[:16]

    store.insert_project_spans(proj_a, [_span(uuid.uuid4().hex, sid_a, ws)])
    store.insert_project_spans(proj_b, [_span(uuid.uuid4().hex, sid_b, ws)])

    rows_a = store.fetch_project_spans(proj_a, ws)
    assert any(r["span_id"] == sid_a for r in rows_a)
    assert not any(r["span_id"] == sid_b for r in rows_a)

    for p in [proj_a, proj_b]:
        store.delete_project_spans(p, ws)


def test_fetch_project_trace_spans():
    store    = _get_store()
    ws       = _ws()
    proj_id  = uuid.uuid4().hex
    trace_a  = uuid.uuid4().hex
    trace_b  = uuid.uuid4().hex
    sid_a    = uuid.uuid4().hex[:16]
    sid_b    = uuid.uuid4().hex[:16]

    store.insert_project_spans(proj_id, [
        _span(trace_a, sid_a, ws),
        _span(trace_b, sid_b, ws),
    ])
    rows = store.fetch_project_trace_spans(proj_id, trace_a, ws)
    ids  = {r["span_id"] for r in rows}
    assert sid_a in ids
    assert sid_b not in ids
    store.delete_project_spans(proj_id, ws)


def test_fetch_project_spans_stats_batch():
    store    = _get_store()
    ws       = _ws()
    proj_id  = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex

    store.insert_project_spans(proj_id, [
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.LLM_CALL,    offset_seconds=0),
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.LLM_CALL,    offset_seconds=1),
        _span(trace_id, uuid.uuid4().hex[:16], ws, kind=SpanKind.TOOL_INVOKE, offset_seconds=2),
    ])
    stats = store.fetch_project_spans_stats_batch(proj_id, [trace_id], ws)
    assert trace_id in stats
    s = stats[trace_id]
    assert s["span_count"] == 3
    assert s["llm_calls"]  == 2
    store.delete_project_spans(proj_id, ws)


def test_fetch_project_spans_stats_batch_empty():
    store = _get_store()
    assert store.fetch_project_spans_stats_batch("p", [], "ws") == {}


def test_delete_project_spans():
    store    = _get_store()
    ws       = _ws()
    proj_id  = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex
    span_ids = [uuid.uuid4().hex[:16] for _ in range(3)]

    store.insert_project_spans(proj_id, [_span(trace_id, sid, ws) for sid in span_ids])
    store.delete_project_spans(proj_id, ws)

    import time
    for _ in range(10):
        rows = store.fetch_project_spans(proj_id, ws)
        if len(rows) == 0:
            break
        time.sleep(1)

    assert store.fetch_project_spans(proj_id, ws) == []


def test_workspace_isolation_fetch_trace_spans():
    """Spans from a different workspace must not be returned."""
    store    = _get_store()
    ws_a     = _ws()
    ws_b     = _ws()
    trace_id = uuid.uuid4().hex
    sid_a    = uuid.uuid4().hex[:16]
    sid_b    = uuid.uuid4().hex[:16]

    store.insert_spans([_span(trace_id, sid_a, ws_a), _span(trace_id, sid_b, ws_b)])
    rows = store.fetch_trace_spans(trace_id, ws_a)
    ids  = {r["span_id"] for r in rows}
    assert sid_a in ids
    assert sid_b not in ids, "Span from workspace B leaked into workspace A results"

    _cleanup(store, ws_a)
    _cleanup(store, ws_b)


def test_project_spans_stats_includes_total_ms():
    """fetch_project_spans_stats_batch must return total_ms."""
    store    = _get_store()
    ws       = _ws()
    proj_id  = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex

    store.insert_project_spans(proj_id, [
        _span(trace_id, uuid.uuid4().hex[:16], ws, offset_seconds=0),
        _span(trace_id, uuid.uuid4().hex[:16], ws, offset_seconds=1),
    ])
    stats = store.fetch_project_spans_stats_batch(proj_id, [trace_id], ws)
    assert trace_id in stats
    assert "total_ms" in stats[trace_id]
    assert stats[trace_id]["total_ms"] >= 0
    store.delete_project_spans(proj_id, ws)
