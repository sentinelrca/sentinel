"""Unit tests for insert_spans_dedup — no real ClickHouse required."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus


def _span(span_id: str, trace_id: str = "trace-1") -> NormalizedSpan:
    now = datetime.now(timezone.utc)
    return NormalizedSpan(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=None,
        name="test_span",
        kind=SpanKind.CHAIN,
        status=SpanStatus.OK,
        start_time=now,
        end_time=now,
        workspace_id="ws-test",
    )


@patch("sentinel_pipeline.db.clickhouse.insert_spans")
@patch("sentinel_pipeline.db.clickhouse._get_client")
def test_dedup_skips_existing_spans(mock_get_client, mock_insert_spans):
    from sentinel_pipeline.db.clickhouse import insert_spans_dedup

    client = MagicMock()
    # Simulate span-1 already exists in ClickHouse
    client.execute.return_value = [("span-1",)]
    mock_get_client.return_value = client

    spans = [_span("span-1"), _span("span-2")]
    result = insert_spans_dedup(spans)

    # Only span-2 should be inserted
    assert result == 1
    inserted = mock_insert_spans.call_args[0][0]
    assert len(inserted) == 1
    assert inserted[0].span_id == "span-2"


@patch("sentinel_pipeline.db.clickhouse.insert_spans")
@patch("sentinel_pipeline.db.clickhouse._get_client")
def test_dedup_inserts_all_when_none_exist(mock_get_client, mock_insert_spans):
    from sentinel_pipeline.db.clickhouse import insert_spans_dedup

    client = MagicMock()
    client.execute.return_value = []  # nothing exists
    mock_get_client.return_value = client

    spans = [_span("span-1"), _span("span-2"), _span("span-3")]
    result = insert_spans_dedup(spans)

    assert result == 3
    inserted = mock_insert_spans.call_args[0][0]
    assert {s.span_id for s in inserted} == {"span-1", "span-2", "span-3"}


@patch("sentinel_pipeline.db.clickhouse.insert_spans")
@patch("sentinel_pipeline.db.clickhouse._get_client")
def test_dedup_skips_all_when_all_exist(mock_get_client, mock_insert_spans):
    from sentinel_pipeline.db.clickhouse import insert_spans_dedup

    client = MagicMock()
    client.execute.return_value = [("span-1",), ("span-2",)]
    mock_get_client.return_value = client

    spans = [_span("span-1"), _span("span-2")]
    result = insert_spans_dedup(spans)

    assert result == 0
    mock_insert_spans.assert_not_called()


@patch("sentinel_pipeline.db.clickhouse.insert_spans")
@patch("sentinel_pipeline.db.clickhouse._get_client")
def test_dedup_returns_zero_for_empty_input(mock_get_client, mock_insert_spans):
    from sentinel_pipeline.db.clickhouse import insert_spans_dedup

    result = insert_spans_dedup([])

    assert result == 0
    mock_get_client.assert_not_called()
    mock_insert_spans.assert_not_called()


@patch("sentinel_pipeline.db.clickhouse.insert_spans")
@patch("sentinel_pipeline.db.clickhouse._get_client")
def test_dedup_falls_back_to_full_insert_on_check_error(mock_get_client, mock_insert_spans):
    from sentinel_pipeline.db.clickhouse import insert_spans_dedup

    client = MagicMock()
    client.execute.side_effect = Exception("ClickHouse unavailable")
    mock_get_client.return_value = client

    spans = [_span("span-1"), _span("span-2")]
    # Should not raise; should fall back to inserting everything
    result = insert_spans_dedup(spans)

    assert result == 2
    mock_insert_spans.assert_called_once()


@patch("sentinel_pipeline.db.clickhouse._get_client")
def test_dedup_uses_workspace_id_in_query(mock_get_client):
    from sentinel_pipeline.db.clickhouse import insert_spans_dedup

    client = MagicMock()
    client.execute.return_value = []
    mock_get_client.return_value = client

    spans = [_span("span-1")]
    with patch("sentinel_pipeline.db.clickhouse.insert_spans"):
        insert_spans_dedup(spans)

    # Verify workspace_id is passed as a query parameter (not interpolated into SQL)
    call_kwargs = client.execute.call_args
    params = call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1].get("params", {})
    assert params.get("ws") == "ws-test"
