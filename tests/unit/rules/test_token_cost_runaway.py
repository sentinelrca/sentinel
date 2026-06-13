from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.token_cost_runaway import (
    TokenCostRunawayDetector,
    _MAX_INPUT_TOKENS,
    _MAX_OUTPUT_TOKENS,
    _MAX_TOTAL_TOKENS,
)

detector = TokenCostRunawayDetector()

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _llm_span(span_id, input_tokens=0, output_tokens=0, model="gpt-4o", offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=500),
        workspace_id="ws1",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )


def _tool_span(span_id, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=200),
        workspace_id="ws1",
    )


# ---------------------------------------------------------------------------
# Should fire
# ---------------------------------------------------------------------------

def test_fires_on_input_token_breach():
    spans = [_llm_span("big_call", input_tokens=_MAX_INPUT_TOKENS + 1, output_tokens=100)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Expected insight when input tokens exceed threshold"
    assert insights[0].detector_id == "token_cost_runaway"
    ev = insights[0].evidence
    assert ev["total_input_tokens"] == _MAX_INPUT_TOKENS + 1
    assert "input tokens" in insights[0].detail


def test_fires_on_output_token_breach():
    spans = [_llm_span("verbose_call", input_tokens=100, output_tokens=_MAX_OUTPUT_TOKENS + 1)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Expected insight when output tokens exceed threshold"
    assert "output tokens" in insights[0].detail


def test_fires_when_aggregate_spans_exceed_input_threshold():
    # No single LLM call exceeds _MAX_INPUT_TOKENS individually, but across
    # two calls the aggregate total_input crosses the threshold. This is the
    # realistic "death by a thousand moderate calls" pattern.
    per_span = _MAX_INPUT_TOKENS // 2 + 1   # e.g. 25_001 — below per-call threshold
    spans = [
        _llm_span("call_a", input_tokens=per_span, output_tokens=0, offset_ms=0),
        _llm_span("call_b", input_tokens=per_span, output_tokens=0, offset_ms=600),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Expected insight when aggregate input tokens exceed threshold"
    ev = insights[0].evidence
    assert ev["total_input_tokens"] == per_span * 2
    assert ev["total_input_tokens"] > _MAX_INPUT_TOKENS


def test_fires_with_multiple_llm_spans_summed():
    # 10 spans × 6k input each = 60k → exceeds 50k
    spans = [_llm_span(f"call_{i}", input_tokens=6_000, offset_ms=i * 200) for i in range(10)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].evidence["total_input_tokens"] == 60_000


# ---------------------------------------------------------------------------
# Should not fire
# ---------------------------------------------------------------------------

def test_no_fire_when_all_below_thresholds():
    spans = [_llm_span("normal_call", input_tokens=1_000, output_tokens=500)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_on_empty_graph():
    graph = build_graph([])
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_on_tool_spans_only():
    """Tool spans carry no tokens — should never trigger."""
    spans = [_tool_span(f"tool_{i}", offset_ms=i * 200) for i in range(20)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_exactly_at_threshold():
    """Exactly at threshold is not a breach (strict >)."""
    spans = [_llm_span("edge", input_tokens=_MAX_INPUT_TOKENS, output_tokens=_MAX_OUTPUT_TOKENS)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


# ---------------------------------------------------------------------------
# Evidence quality
# ---------------------------------------------------------------------------

def test_evidence_identifies_top_consumers():
    spans = [
        _llm_span("small",  input_tokens=100,    output_tokens=50,  offset_ms=0),
        _llm_span("medium", input_tokens=10_000,  output_tokens=500, offset_ms=200),
        _llm_span("large",  input_tokens=_MAX_INPUT_TOKENS + 1, output_tokens=200, offset_ms=400),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    ev = insights[0].evidence
    assert "top_consumers" in ev
    # Highest-consuming span should be first
    assert ev["top_consumers"][0]["span_id"] == "large"
    assert ev["thresholds"]["max_input_tokens"] == _MAX_INPUT_TOKENS


def test_affected_span_ids_point_to_top_consumers():
    spans = [
        _llm_span("heavy", input_tokens=_MAX_INPUT_TOKENS + 1, offset_ms=0),
        _llm_span("light", input_tokens=100, offset_ms=200),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert "heavy" in insights[0].affected_span_ids
