"""Unit tests for the retry_storm rule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.rules.retry_storm import RetryStormRule
from sentinel_pipeline.signals.extractor import extract_signals

rule = RetryStormRule()
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.ERROR,
          retry_count=0, parent_id=None, offset_ms=0):
    t = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name=f"tool_{span_id}", kind=kind, status=status,
        start_time=t, end_time=t + timedelta(milliseconds=100),
        workspace_id="ws1", retry_count=retry_count,
    )


def test_fires_on_tool_retried_3_times_with_error():
    spans = [_span("s1", retry_count=3, status=SpanStatus.ERROR)]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert insights[0].rule_id == "retry_storm"
    assert insights[0].evidence["retry_count"] == 3


def test_fires_on_tool_retried_more_than_3_times():
    spans = [_span("s1", retry_count=5, status=SpanStatus.ERROR)]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert insights[0].evidence["retry_count"] == 5


def test_no_fire_when_retry_count_below_threshold():
    """2 retries is not enough to trigger."""
    spans = [_span("s1", retry_count=2, status=SpanStatus.ERROR)]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_when_high_retry_but_status_ok():
    """Retry count >= 3 but span succeeded — rule must NOT fire."""
    spans = [_span("s1", retry_count=3, status=SpanStatus.OK)]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_on_empty_graph():
    graph = build_graph([])
    assert not rule.evaluate(graph, extract_signals(graph))


def test_fires_only_on_failing_span_in_mixed_trace():
    """Only the span with error + high retry count should fire."""
    spans = [
        _span("ok_span",  retry_count=4, status=SpanStatus.OK,    offset_ms=0),
        _span("err_span", retry_count=3, status=SpanStatus.ERROR,  offset_ms=100),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert len(insights) == 1
    assert insights[0].evidence["span_id"] == "err_span"


def test_multiple_failing_spans_each_fire():
    spans = [
        _span("s1", retry_count=3, status=SpanStatus.ERROR, offset_ms=0),
        _span("s2", retry_count=4, status=SpanStatus.ERROR, offset_ms=100),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert len(insights) == 2


def test_insight_includes_affected_span_id():
    spans = [_span("s1", retry_count=3, status=SpanStatus.ERROR)]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert "s1" in insights[0].affected_span_ids
