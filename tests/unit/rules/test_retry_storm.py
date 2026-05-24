from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.retry_storm import RetryStormDetector

detector = RetryStormDetector()

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind=SpanKind.TOOL_INVOKE, retry_count=0, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=500),
        workspace_id="ws1",
        retry_count=retry_count,
    )


def test_fires_when_single_span_retried_many_times():
    """One span with 4 retries should trigger the detector."""
    spans = [_span("flaky_tool", retry_count=4)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Expected insight for single span with 4 retries"
    assert insights[0].detector_id == "retry_storm"
    assert insights[0].evidence["max_retries"] == 4


def test_fires_when_many_spans_each_retried():
    """5 spans each retried once should exceed the total threshold."""
    spans = [_span(f"tool_{i}", retry_count=1, offset_ms=i * 600) for i in range(5)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Expected insight when total retries >= 5"
    assert insights[0].evidence["total_retries"] == 5


def test_no_fire_when_retries_below_both_thresholds():
    """2 retries total on one span should not fire."""
    spans = [_span("tool_a", retry_count=2)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert not insights


def test_no_fire_when_no_retries():
    """Clean trace with no retries should never fire."""
    spans = [_span("tool_a", retry_count=0), _span("tool_b", retry_count=0, offset_ms=600)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert not insights


# --- structural retry inference (no explicit retry_count from connector) ---

def _struct_span(span_id, name, parent_id, status=SpanStatus.OK, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name=name, kind=SpanKind.TOOL_INVOKE, status=status,
        start_time=t0, end_time=t0 + timedelta(milliseconds=500),
        workspace_id="ws1",
    )


def test_structural_retry_inferred_from_sibling_errors():
    """Three failed siblings + one success → inferred retry_count=3, meets threshold."""
    root = _span("root", kind=SpanKind.CHAIN)
    # Four attempts at "call_api" — first three fail, fourth succeeds
    attempt_1 = _struct_span("a1", "call_api", "root", status=SpanStatus.ERROR,   offset_ms=0)
    attempt_2 = _struct_span("a2", "call_api", "root", status=SpanStatus.TIMEOUT, offset_ms=600)
    attempt_3 = _struct_span("a3", "call_api", "root", status=SpanStatus.ERROR,   offset_ms=1200)
    attempt_4 = _struct_span("a4", "call_api", "root", status=SpanStatus.OK,      offset_ms=1800)
    graph = build_graph([root, attempt_1, attempt_2, attempt_3, attempt_4])
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Expected retry_storm to fire via structural inference"
    assert insights[0].evidence["max_retries"] == 3
    assert "a4" in insights[0].affected_span_ids


def test_structural_retry_not_inferred_when_all_succeed():
    """Same tool called multiple times, all succeeding — not a retry, should not fire."""
    root = _span("root", kind=SpanKind.CHAIN)
    call_1 = _struct_span("c1", "search", "root", status=SpanStatus.OK, offset_ms=0)
    call_2 = _struct_span("c2", "search", "root", status=SpanStatus.OK, offset_ms=600)
    call_3 = _struct_span("c3", "search", "root", status=SpanStatus.OK, offset_ms=1200)
    graph = build_graph([root, call_1, call_2, call_3])
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_structural_retry_does_not_overwrite_explicit_retry_count():
    """Explicit retry_count from connector must not be overwritten by structural inference."""
    root = _span("root", kind=SpanKind.CHAIN)
    # First attempt errors, second has explicit retry_count=1 from connector
    attempt_1 = _struct_span("b1", "llm_call", "root", status=SpanStatus.ERROR, offset_ms=0)
    attempt_2 = NormalizedSpan(
        span_id="b2", trace_id="t1", parent_span_id="root",
        name="llm_call", kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=_T0 + timedelta(milliseconds=600),
        end_time=_T0 + timedelta(milliseconds=1100),
        workspace_id="ws1",
        retry_count=1,  # explicit from connector
    )
    graph = build_graph([root, attempt_1, attempt_2])
    # retry_count should remain 1, not be overwritten with inferred value
    assert graph.nodes["b2"].retry_count == 1


def test_evidence_identifies_worst_span():
    """Evidence should point to the span with the highest retry count."""
    spans = [
        _span("stable_tool",  retry_count=1, offset_ms=0),
        _span("flaky_tool",   retry_count=5, offset_ms=600),
        _span("another_tool", retry_count=1, offset_ms=1200),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    ev = insights[0].evidence
    assert ev["worst_span_name"] == "flaky_tool"
    assert ev["worst_span_id"] == "flaky_tool"
    assert ev["max_retries"] == 5
    assert ev["total_retries"] == 7
