from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.sequential_tools import SequentialToolsDetector

rule = SequentialToolsDetector()


def _tool_span(span_id, parent_id, offset_ms, duration_ms=1000):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name=span_id, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws1",
    )


def _chain_span(span_id):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.CHAIN, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=3000),
        workspace_id="ws1",
    )


def test_fires_on_serial_independent_tools():
    """Two sibling tools executed back-to-back → should fire."""
    root = _chain_span("root")
    # tool_a: 0ms → 1000ms; tool_b: 1000ms → 2000ms (serial, no overlap)
    tool_a = _tool_span("tool_a", parent_id="root", offset_ms=0,    duration_ms=1000)
    tool_b = _tool_span("tool_b", parent_id="root", offset_ms=1000, duration_ms=1000)
    graph    = build_graph([root, tool_a, tool_b])
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert insights, "Expected insight for serial tool_a → tool_b"
    assert insights[0].detector_id == "sequential_tools"


def test_no_fire_below_threshold():
    """Serial tools saving < 500ms should not fire."""
    root   = _chain_span("root")
    tool_a = _tool_span("tool_a", parent_id="root", offset_ms=0,   duration_ms=200)
    tool_b = _tool_span("tool_b", parent_id="root", offset_ms=200, duration_ms=200)
    graph    = build_graph([root, tool_a, tool_b])
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert not insights, "Should not fire when saving < 500ms"


def test_no_fire_on_overlapping_tools():
    """Overlapping tools are already effectively parallel — no fire."""
    root   = _chain_span("root")
    tool_a = _tool_span("tool_a", parent_id="root", offset_ms=0,   duration_ms=1000)
    tool_b = _tool_span("tool_b", parent_id="root", offset_ms=500, duration_ms=1000)
    graph    = build_graph([root, tool_a, tool_b])
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert not insights


def test_insight_includes_tool_names_and_saving():
    root   = _chain_span("root")
    tool_a = _tool_span("search_web", parent_id="root", offset_ms=0,    duration_ms=1500)
    tool_b = _tool_span("query_db",  parent_id="root", offset_ms=1500, duration_ms=1500)
    graph    = build_graph([root, tool_a, tool_b])
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert insights
    ev = insights[0].evidence
    assert ev["tool_a"] == "search_web"
    assert ev["tool_b"] == "query_db"
    assert ev["saved_ms"] >= 1500
