"""Unit tests for project_spans ClickHouse functions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from sentinel_pipeline.db.clickhouse import (
    delete_project_spans,
    fetch_project_spans,
    insert_project_spans,
)
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)


def _span(span_id: str, trace_id: str = "trace-1") -> NormalizedSpan:
    return NormalizedSpan(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=None,
        name=span_id,
        kind=SpanKind.LLM_CALL,
        status=SpanStatus.OK,
        start_time=_T0,
        end_time=_T1,
        workspace_id="ws-1",
        input_tokens=10,
        output_tokens=5,
    )


# ---------------------------------------------------------------------------
# insert_project_spans
# ---------------------------------------------------------------------------

def test_insert_project_spans_calls_execute():
    mock_client = MagicMock()
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        spans = [_span("s1"), _span("s2")]
        insert_project_spans("proj-1", spans)

    mock_client.execute.assert_called_once()
    call_args = mock_client.execute.call_args
    assert call_args[0][0] == "INSERT INTO project_spans VALUES"
    rows = call_args[0][1]
    assert len(rows) == 2
    assert rows[0][0] == "proj-1"   # project_id first
    assert rows[0][1] == "trace-1"  # trace_id
    assert rows[0][2] == "s1"       # span_id


def test_insert_project_spans_empty_list_is_noop():
    mock_client = MagicMock()
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        insert_project_spans("proj-1", [])
    mock_client.execute.assert_not_called()


def test_insert_project_spans_raises_on_client_error():
    mock_client = MagicMock()
    mock_client.execute.side_effect = RuntimeError("CH down")
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        with pytest.raises(RuntimeError):
            insert_project_spans("proj-1", [_span("s1")])


def test_insert_project_spans_serializes_attributes():
    mock_client = MagicMock()
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        span = _span("s1")
        span = span.model_copy(update={"attributes": {"key": "value"}})
        insert_project_spans("proj-1", [span])

    rows = mock_client.execute.call_args[0][1]
    attributes_json = rows[0][-1]
    assert json.loads(attributes_json) == {"key": "value"}


# ---------------------------------------------------------------------------
# fetch_project_spans
# ---------------------------------------------------------------------------

def _raw_row(project_id="proj-1", trace_id="trace-1", span_id="s1"):
    return (
        project_id, trace_id, span_id, "",
        "ws-1", "llm_call", "llm_call", "ok",
        _T0, _T1,
        "", "", 10, 5, 0, "", "{}",
    )


def test_fetch_project_spans_returns_dicts():
    mock_client = MagicMock()
    mock_client.execute.return_value = [_raw_row()]
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        rows = fetch_project_spans("proj-1", "ws-1")

    assert len(rows) == 1
    assert rows[0]["project_id"] == "proj-1"
    assert rows[0]["trace_id"] == "trace-1"
    assert rows[0]["span_id"] == "s1"
    assert rows[0]["workspace_id"] == "ws-1"


def test_fetch_project_spans_passes_correct_params():
    mock_client = MagicMock()
    mock_client.execute.return_value = []
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        fetch_project_spans("proj-abc", "ws-xyz")

    _, kwargs = mock_client.execute.call_args
    params = mock_client.execute.call_args[0][1]
    assert params["project_id"] == "proj-abc"
    assert params["workspace_id"] == "ws-xyz"


def test_fetch_project_spans_returns_empty_on_error():
    mock_client = MagicMock()
    mock_client.execute.side_effect = RuntimeError("CH down")
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        rows = fetch_project_spans("proj-1", "ws-1")
    assert rows == []


def test_fetch_project_spans_empty_result():
    mock_client = MagicMock()
    mock_client.execute.return_value = []
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        rows = fetch_project_spans("proj-1", "ws-1")
    assert rows == []


# ---------------------------------------------------------------------------
# delete_project_spans
# ---------------------------------------------------------------------------

def test_delete_project_spans_calls_alter_table():
    mock_client = MagicMock()
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        delete_project_spans("proj-1")

    mock_client.execute.assert_called_once()
    sql = mock_client.execute.call_args[0][0]
    assert "ALTER TABLE project_spans DELETE" in sql
    params = mock_client.execute.call_args[0][1]
    assert params["project_id"] == "proj-1"


def test_delete_project_spans_swallows_error():
    mock_client = MagicMock()
    mock_client.execute.side_effect = RuntimeError("CH down")
    with patch("sentinel_pipeline.db.clickhouse._get_client", return_value=mock_client):
        delete_project_spans("proj-1")  # must not raise
