from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.context_cache_opportunity import ContextCacheOpportunityDetector

detector = ContextCacheOpportunityDetector()

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _llm(span_id, model="gpt-4o", input_tokens=None, output_tokens=50, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=1000),
        workspace_id="ws1",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _tool(span_id, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=200),
        workspace_id="ws1",
    )


# --- fires ---

def test_fires_on_repeated_large_context_same_model():
    """3 calls to same model with identical large input → should fire."""
    spans = [
        _llm("call_1", input_tokens=4096, offset_ms=0),
        _llm("call_2", input_tokens=4096, offset_ms=1100),
        _llm("call_3", input_tokens=4096, offset_ms=2200),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].detector_id == "context_cache_opportunity"
    ev = insights[0].evidence
    assert ev["repeated_calls"] == 3
    assert ev["input_tokens_per_call"] == 4096
    assert ev["wasted_tokens"] == 4096 * 2


def test_fires_within_similarity_tolerance():
    """Input tokens within 5% of each other should be treated as same context."""
    spans = [
        _llm("call_1", input_tokens=4000, offset_ms=0),
        _llm("call_2", input_tokens=4100, offset_ms=1100),  # 2.5% variance — same cluster
        _llm("call_3", input_tokens=4050, offset_ms=2200),  # 1.25% variance — same cluster
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Calls within 5% tolerance should cluster together"


def test_evidence_reports_wasted_tokens():
    """Wasted tokens = input_tokens × (calls - 1)."""
    spans = [
        _llm("c1", input_tokens=8192, offset_ms=0),
        _llm("c2", input_tokens=8192, offset_ms=1100),
        _llm("c3", input_tokens=8192, offset_ms=2200),
        _llm("c4", input_tokens=8192, offset_ms=3300),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert insights[0].evidence["wasted_tokens"] == 8192 * 3


# --- model-specific recommendation ---

def test_recommendation_is_model_specific_claude():
    spans = [
        _llm("c1", model="claude-3-5-sonnet", input_tokens=2048, offset_ms=0),
        _llm("c2", model="claude-3-5-sonnet", input_tokens=2048, offset_ms=1100),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert "cache_control" in insights[0].recommendation


def test_recommendation_is_model_specific_openai():
    spans = [
        _llm("c1", model="gpt-4o", input_tokens=2048, offset_ms=0),
        _llm("c2", model="gpt-4o", input_tokens=2048, offset_ms=1100),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert "automatic" in insights[0].recommendation.lower()


def test_recommendation_is_model_specific_gemini():
    spans = [
        _llm("c1", model="gemini-1.5-pro", input_tokens=2048, offset_ms=0),
        _llm("c2", model="gemini-1.5-pro", input_tokens=2048, offset_ms=1100),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    assert "gemini" in insights[0].recommendation.lower()


# --- does not fire ---

def test_no_fire_on_single_llm_call():
    """Only one LLM call — nothing to compare against."""
    spans = [_llm("only_call", input_tokens=4096)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert detector.evaluate(graph, signals) is None


def test_no_fire_below_min_input_tokens():
    """Small prompts (< 1024 tokens) are not worth caching."""
    spans = [
        _llm("c1", input_tokens=200, offset_ms=0),
        _llm("c2", input_tokens=200, offset_ms=1100),
        _llm("c3", input_tokens=200, offset_ms=2200),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_on_tool_only_trace():
    """No LLM calls → skip entirely."""
    spans = [_tool("t1"), _tool("t2", offset_ms=300)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert detector.evaluate(graph, signals) is None


def test_no_fire_when_input_tokens_vary_widely():
    """Calls with very different input sizes are different prompts — not a cache opportunity."""
    spans = [
        _llm("c1", input_tokens=1024, offset_ms=0),
        _llm("c2", input_tokens=8192, offset_ms=1100),  # 8× larger — different prompt
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_when_models_differ():
    """Same input token count but different models → separate groups, each below threshold."""
    spans = [
        _llm("c1", model="gpt-4o",       input_tokens=4096, offset_ms=0),
        _llm("c2", model="claude-3-haiku", input_tokens=4096, offset_ms=1100),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_separate_insights_per_model():
    """Two models each with repeated large contexts → two separate insights."""
    spans = [
        _llm("g1", model="gpt-4o",        input_tokens=4096, offset_ms=0),
        _llm("g2", model="gpt-4o",        input_tokens=4096, offset_ms=1100),
        _llm("c1", model="claude-3-haiku", input_tokens=2048, offset_ms=2200),
        _llm("c2", model="claude-3-haiku", input_tokens=2048, offset_ms=3300),
    ]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights and len(insights) == 2
    models = {i.evidence["model"] for i in insights}
    assert "gpt-4o" in models and "claude-3-haiku" in models
