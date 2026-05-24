from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.latency_spike import LatencySpikeDetector, _context_window

detector = LatencySpikeDetector()

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _llm(span_id, duration_ms=1000, model="gpt-4o",
         input_tokens=None, output_tokens=None, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws1",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _tool(span_id, duration_ms=500, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws1",
    )


# --- no LLM spans ---

def test_no_fire_on_tool_only_trace():
    """Traces with no LLM calls are skipped entirely."""
    spans = [_tool("tool_a"), _tool("tool_b", offset_ms=600)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert detector.evaluate(graph, signals) is None


# --- low_throughput ---

def test_fires_on_low_throughput():
    """One LLM call 4× slower than same-model peers should trigger low_throughput."""
    # 3 fast calls: 100 tokens in 1000ms = 100 tok/s
    # 1 slow call:  100 tokens in 8000ms = 12.5 tok/s  (< 100/3 = 33.3 tok/s)
    spans = [
        _llm("fast_1", duration_ms=1000, output_tokens=100, offset_ms=0),
        _llm("fast_2", duration_ms=1000, output_tokens=100, offset_ms=1100),
        _llm("fast_3", duration_ms=1000, output_tokens=100, offset_ms=2200),
        _llm("slow_1", duration_ms=8000, output_tokens=100, offset_ms=3300),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    throughput_insights = [i for i in insights if "throughput" in i.title.lower() or "Low throughput" in i.title]
    assert throughput_insights, "Expected a low_throughput insight"
    ev = throughput_insights[0].evidence
    assert ev["slowdown_factor"] > 3.0
    assert throughput_insights[0].affected_span_ids == ["slow_1"]


def test_no_fire_low_throughput_with_insufficient_peers():
    """Only 2 same-model spans (1 peer) — below minimum, should not fire."""
    spans = [
        _llm("fast_1", duration_ms=1000, output_tokens=100),
        _llm("slow_1", duration_ms=8000, output_tokens=100, offset_ms=1100),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals) or []
    throughput = [i for i in insights if "throughput" in i.title.lower()]
    assert not throughput


def test_no_fire_low_throughput_mixed_models():
    """Spans from different models are not compared against each other."""
    spans = [
        _llm("gpt_call",    duration_ms=1000, model="gpt-4o",          output_tokens=100),
        _llm("claude_call", duration_ms=8000, model="claude-3-haiku",   output_tokens=100, offset_ms=1100),
        _llm("gemini_call", duration_ms=1000, model="gemini-1.5-flash", output_tokens=100, offset_ms=9200),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals) or []
    throughput = [i for i in insights if "throughput" in i.title.lower()]
    assert not throughput


# --- oversized_context ---

def test_fires_on_oversized_context():
    """Input tokens > 75% of model context window should trigger oversized_context."""
    # gpt-4 context = 8192; 75% = 6144; send 7000 → fires
    spans = [_llm("big_prompt", model="gpt-4", input_tokens=7000, duration_ms=5000)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    ctx_insights = [i for i in insights if "context" in i.title.lower()]
    assert ctx_insights
    ev = ctx_insights[0].evidence
    assert ev["utilization"] > 0.75
    assert ev["context_window"] == 8192


def test_no_fire_oversized_context_within_limit():
    """Input tokens below threshold should not fire."""
    # gpt-4o context = 128000; 50% = 64000 — under threshold
    spans = [_llm("normal_prompt", model="gpt-4o", input_tokens=64_000, duration_ms=2000)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals) or []
    ctx_insights = [i for i in insights if "context" in i.title.lower()]
    assert not ctx_insights


def test_no_fire_oversized_context_unknown_model():
    """Unknown model — cannot determine context window, should skip."""
    spans = [_llm("call", model="my-custom-llm", input_tokens=50_000, duration_ms=2000)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals) or []
    ctx_insights = [i for i in insights if "context" in i.title.lower()]
    assert not ctx_insights


# --- critical_path_bottleneck ---

def test_fires_on_critical_path_domination():
    """Single LLM span taking >60% of trace time should fire critical_path."""
    # LLM span: 8000ms; total trace ~10000ms → 80%
    spans = [
        _llm("slow_llm",   duration_ms=8000, offset_ms=0),
        _tool("quick_tool", duration_ms=2000, offset_ms=8000),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    cp_insights = [i for i in insights if "dominates" in i.title.lower()]
    assert cp_insights
    assert cp_insights[0].evidence["ratio"] > 0.60
    assert cp_insights[0].severity.value == "high"


def test_no_fire_critical_path_balanced_trace():
    """Balanced trace where no single LLM span dominates should not fire."""
    spans = [
        _llm("llm_1", duration_ms=1000, offset_ms=0),
        _llm("llm_2", duration_ms=1000, offset_ms=1100),
        _llm("llm_3", duration_ms=1000, offset_ms=2200),
        _tool("tool", duration_ms=7000, offset_ms=3300),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals) or []
    cp_insights = [i for i in insights if "dominates" in i.title.lower()]
    assert not cp_insights


# --- context window lookup ---

def test_context_window_prefix_match():
    assert _context_window("gpt-4o-2024-11-20") == 128_000
    assert _context_window("claude-3-haiku-20240307") == 200_000
    assert _context_window("gemini-1.5-pro-002") == 1_048_576


def test_context_window_unknown_model():
    assert _context_window("my-custom-model-v1") is None
    assert _context_window("") is None
