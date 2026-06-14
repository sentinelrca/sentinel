"""Tests for the SpanStore protocol, factory, and Tinybird backend."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.storage import get_span_store, reset_span_store
from sentinel_pipeline.storage.base import SpanStore
from sentinel_pipeline.storage.tinybird import TinybirdSpanStore, _dt_to_sql, _safe_id

_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 1, 12, 0, 1, tzinfo=timezone.utc)


_WS_ID    = "d98d339c-ed2b-4527-997e-b0983954fccd"
_TRACE_ID = "2bef1ea14303386d5165d4713faa1418"
_PROJ_ID  = "5770266b-3a37-48eb-bc4e-3dbab1588a02"


def _span(span_id="sp-001", trace_id=_TRACE_ID, workspace_id=_WS_ID) -> NormalizedSpan:
    return NormalizedSpan(
        span_id=span_id, trace_id=trace_id, parent_span_id=None,
        name="test", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=_T0, end_time=_T1, workspace_id=workspace_id,
    )


# ---------------------------------------------------------------------------
# Factory — get_span_store()
# ---------------------------------------------------------------------------

def test_factory_returns_clickhouse_by_default():
    reset_span_store()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SENTINEL_STORAGE_BACKEND", None)
        from sentinel_pipeline.storage.clickhouse import ClickHouseSpanStore
        store = get_span_store()
        assert isinstance(store, ClickHouseSpanStore)
    reset_span_store()


def test_factory_returns_tinybird_when_configured():
    reset_span_store()
    with patch.dict(os.environ, {
        "SENTINEL_STORAGE_BACKEND": "tinybird",
        "TINYBIRD_API_KEY": "tb-test-key",
    }):
        from sentinel_pipeline.storage.tinybird import TinybirdSpanStore
        store = get_span_store()
        assert isinstance(store, TinybirdSpanStore)
    reset_span_store()


def test_factory_raises_on_unknown_backend():
    reset_span_store()
    with patch.dict(os.environ, {"SENTINEL_STORAGE_BACKEND": "bogus"}):
        with pytest.raises(ValueError, match="Unknown SENTINEL_STORAGE_BACKEND"):
            get_span_store()
    reset_span_store()


def test_factory_returns_same_instance_on_repeated_calls():
    reset_span_store()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SENTINEL_STORAGE_BACKEND", None)
        a = get_span_store()
        b = get_span_store()
        assert a is b
    reset_span_store()


def test_reset_span_store_clears_singleton():
    reset_span_store()
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SENTINEL_STORAGE_BACKEND", None)
        a = get_span_store()
        reset_span_store()
        b = get_span_store()
        assert a is not b
    reset_span_store()


def test_factory_raises_when_tinybird_key_missing():
    reset_span_store()
    env = {"SENTINEL_STORAGE_BACKEND": "tinybird"}
    env.pop("TINYBIRD_API_KEY", None)
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("TINYBIRD_API_KEY", None)
        with pytest.raises(RuntimeError, match="TINYBIRD_API_KEY"):
            get_span_store()
    reset_span_store()


def test_clickhouse_store_satisfies_protocol():
    from sentinel_pipeline.storage.clickhouse import ClickHouseSpanStore
    assert isinstance(ClickHouseSpanStore(), SpanStore)


def test_tinybird_store_satisfies_protocol():
    with patch.dict(os.environ, {"TINYBIRD_API_KEY": "tb-key"}):
        assert isinstance(TinybirdSpanStore(), SpanStore)


# ---------------------------------------------------------------------------
# _safe_id — SQL injection guard
# ---------------------------------------------------------------------------

def test_safe_id_accepts_valid_uuid():
    uuid = "6f97cb8a-1a2b-3c4d-5e6f-7a8b9c0d1e2f"
    assert _safe_id(uuid, "test") == uuid


def test_safe_id_accepts_hex_string():
    assert _safe_id("abc123DEF456", "test") == "abc123DEF456"


def test_safe_id_rejects_single_quote():
    with pytest.raises(ValueError, match="Unsafe value"):
        _safe_id("ws-1'; DROP TABLE spans;--", "workspace_id")


def test_safe_id_rejects_space():
    with pytest.raises(ValueError, match="Unsafe value"):
        _safe_id("ws 1", "workspace_id")


def test_safe_id_rejects_newline():
    with pytest.raises(ValueError, match="Unsafe value"):
        _safe_id("ws\n1", "workspace_id")


# ---------------------------------------------------------------------------
# _dt_to_sql — datetime formatting for Tinybird SQL
# ---------------------------------------------------------------------------

def test_dt_to_sql_formats_correctly():
    dt = datetime(2026, 6, 1, 12, 34, 56, tzinfo=timezone.utc)
    assert _dt_to_sql(dt) == "2026-06-01 12:34:56"


def test_dt_to_sql_strips_microseconds():
    dt = datetime(2026, 6, 1, 12, 34, 56, 789012, tzinfo=timezone.utc)
    assert _dt_to_sql(dt) == "2026-06-01 12:34:56"


def test_dt_to_sql_converts_to_utc():
    from datetime import timedelta
    tz_plus2 = timezone(timedelta(hours=2))
    dt = datetime(2026, 6, 1, 14, 34, 56, tzinfo=tz_plus2)   # 12:34 UTC
    assert _dt_to_sql(dt) == "2026-06-01 12:34:56"


# ---------------------------------------------------------------------------
# TinybirdSpanStore — HTTP call assertions
# ---------------------------------------------------------------------------

def _tb_store() -> TinybirdSpanStore:
    with patch.dict(os.environ, {
        "TINYBIRD_API_KEY": "tb-test-key",
        "TINYBIRD_HOST":    "https://api.tinybird.co",
    }):
        return TinybirdSpanStore()


def test_insert_spans_posts_ndjson():
    store = _tb_store()
    span  = _span()
    mock_resp = MagicMock(); mock_resp.raise_for_status = MagicMock()

    with patch("sentinel_pipeline.storage.tinybird.httpx.post", return_value=mock_resp) as mock_post:
        store.insert_spans([span])

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0].endswith("/v0/events")
    assert call_kwargs[1]["params"]["name"] == "spans"
    body = call_kwargs[1]["content"].decode()
    row  = json.loads(body)
    assert row["trace_id"]    == span.trace_id
    assert row["workspace_id"] == span.workspace_id
    assert row["kind"]         == "llm_call"
    # Verify timestamp format: no microseconds, no timezone offset
    assert "." not in row["start_time"].split("T")[1].rstrip("Z")[:8]


def test_insert_spans_noop_on_empty():
    store = _tb_store()
    with patch("sentinel_pipeline.storage.tinybird.httpx.post") as mock_post:
        store.insert_spans([])
    mock_post.assert_not_called()


def test_delete_spans_uses_correct_endpoint_and_param():
    """POST /v0/datasources/{name}/delete with delete_condition in POST body."""
    store = _tb_store()
    mock_resp = MagicMock(); mock_resp.raise_for_status = MagicMock()

    with patch("sentinel_pipeline.storage.tinybird.httpx.post", return_value=mock_resp) as mock_post:
        store.delete_spans_older_than("d98d339c-ed2b-4527-997e-b0983954fccd", "2026-01-01 00:00:00")

    # Find the delete call (not the SQL query call)
    delete_call = next(
        c for c in mock_post.call_args_list
        if "/delete" in c[0][0]
    )
    url = delete_call[0][0]
    assert url.endswith("/v0/datasources/spans/delete"), f"Wrong URL: {url}"
    assert "delete_condition" in delete_call[1]["data"]
    assert "d98d339c-ed2b-4527-997e-b0983954fccd" in delete_call[1]["data"]["delete_condition"]


def test_delete_project_spans_uses_correct_endpoint_and_param():
    store = _tb_store()
    mock_resp = MagicMock(); mock_resp.raise_for_status = MagicMock()

    with patch("sentinel_pipeline.storage.tinybird.httpx.post", return_value=mock_resp) as mock_post:
        store.delete_project_spans("5770266b-3a37-48eb-bc4e-3dbab1588a02", "d98d339c-ed2b-4527-997e-b0983954fccd")

    delete_call = next(
        c for c in mock_post.call_args_list
        if "/delete" in c[0][0]
    )
    url = delete_call[0][0]
    assert url.endswith("/v0/datasources/project_spans/delete"), f"Wrong URL: {url}"
    params = delete_call[1]["data"]
    assert "delete_condition" in params
    assert "5770266b-3a37-48eb-bc4e-3dbab1588a02" in params["delete_condition"]
    assert "d98d339c-ed2b-4527-997e-b0983954fccd"   in params["delete_condition"]


def test_fetch_trace_spans_builds_correct_sql():
    store = _tb_store()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": []}

    with patch("sentinel_pipeline.storage.tinybird.httpx.post", return_value=mock_resp) as mock_post:
        store.fetch_trace_spans("2bef1ea14303386d5165d4713faa1418", "d98d339c-ed2b-4527-997e-b0983954fccd")

    sql = mock_post.call_args[1]["data"]["q"]
    assert "trace_id = '2bef1ea14303386d5165d4713faa1418'" in sql
    assert "workspace_id = 'd98d339c-ed2b-4527-997e-b0983954fccd'" in sql
    assert "FORMAT JSON" in sql


def test_fetch_trace_spans_rejects_injection():
    store = _tb_store()
    with pytest.raises(ValueError, match="Unsafe value"):
        store.fetch_trace_spans("'; DROP TABLE spans;--", _WS_ID)


def test_fetch_spans_by_filter_date_format_is_sql_safe():
    """Date values must be formatted as 'YYYY-MM-DD HH:MM:SS', not ISO with offset."""
    store = _tb_store()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": []}

    dt = datetime(2026, 6, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
    with patch("sentinel_pipeline.storage.tinybird.httpx.post", return_value=mock_resp) as mock_post:
        store.fetch_spans_by_filter("d98d339c-ed2b-4527-997e-b0983954fccd", date_from=dt, date_to=dt)

    sql = mock_post.call_args[1]["data"]["q"]
    assert "+00:00" not in sql       # no timezone offset
    assert "123456" not in sql       # no microseconds
    assert "2026-06-01 12:00:00" in sql


def test_ensure_tables_is_noop():
    store = _tb_store()
    with patch("sentinel_pipeline.storage.tinybird.httpx.post") as mock_post:
        store.ensure_tables()   # must not make any HTTP calls
    mock_post.assert_not_called()


def test_insert_project_spans_prepends_project_id():
    store = _tb_store()
    span  = _span()
    mock_resp = MagicMock(); mock_resp.raise_for_status = MagicMock()

    with patch("sentinel_pipeline.storage.tinybird.httpx.post", return_value=mock_resp) as mock_post:
        store.insert_project_spans("5770266b-3a37-48eb-bc4e-3dbab1588a02", [span])

    body = mock_post.call_args[1]["content"].decode()
    row  = json.loads(body)
    assert row["project_id"] == "5770266b-3a37-48eb-bc4e-3dbab1588a02"
    assert row["trace_id"]   == span.trace_id
    # Verify posted to project_spans datasource
    assert mock_post.call_args[1]["params"]["name"] == "project_spans"
