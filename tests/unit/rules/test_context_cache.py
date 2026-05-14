"""Unit tests for the context_cache_opportunity rule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.rules.context_cache import ContextCacheOpportunityRule
from sentinel_pipeline.signals.extractor import extract_signals

rule = ContextCacheOpportunityRule()
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _llm(span_id, input_tokens, offset_ms=0, parent_id=None):
    t = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name="ChatOpenAI", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t, end_time=t + timedelta(milliseconds=50),
        workspace_id="ws1", input_tokens=input_tokens,
    )


def _tool(span_id, offset_ms=0):
    t = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name="search", kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t, end_time=t + timedelta(milliseconds=20),
        workspace_id="ws1",
    )


def test_fires_when_tokens_grow_by_300_or_more():
    """500 → 800 (delta=300) — exactly at threshold, should fire."""
    spans = [
        _llm("s1", input_tokens=500, offset_ms=0),
        _llm("s2", input_tokens=800, offset_ms=100),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert insights[0].rule_id == "context_cache_opportunity"
    assert insights[0].evidence["growing_pairs"] == 1


def test_fires_on_consistent_growth_across_multiple_turns():
    """500 → 800 → 1100 → 1400 — growing 300 tokens each turn."""
    spans = [
        _llm("s1", input_tokens=500,  offset_ms=0),
        _llm("s2", input_tokens=800,  offset_ms=100),
        _llm("s3", input_tokens=1100, offset_ms=200),
        _llm("s4", input_tokens=1400, offset_ms=300),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert insights[0].evidence["llm_call_count"] == 4
    assert insights[0].evidence["growing_pairs"] == 3


def test_no_fire_when_growth_below_threshold():
    """Delta of 299 — just below threshold, must NOT fire."""
    spans = [
        _llm("s1", input_tokens=500, offset_ms=0),
        _llm("s2", input_tokens=799, offset_ms=100),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_when_tokens_stable():
    spans = [
        _llm("s1", input_tokens=500, offset_ms=0),
        _llm("s2", input_tokens=510, offset_ms=100),
        _llm("s3", input_tokens=505, offset_ms=200),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_with_single_llm_call():
    spans = [_llm("s1", input_tokens=1000)]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_when_llm_calls_have_no_input_tokens():
    """LLM calls without token counts should be ignored."""
    spans = [
        _llm("s1", input_tokens=None, offset_ms=0),
        _llm("s2", input_tokens=None, offset_ms=100),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_on_empty_graph():
    graph = build_graph([])
    assert not rule.evaluate(graph, extract_signals(graph))


def test_non_llm_spans_ignored_in_calculation():
    """Tool calls between LLM calls should not affect the token comparison."""
    spans = [
        _llm("s1",   input_tokens=500, offset_ms=0),
        _tool("t1",  offset_ms=60),
        _llm("s2",   input_tokens=900, offset_ms=100),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert insights[0].evidence["growing_pairs"] == 1


def test_evidence_contains_growth_summary():
    spans = [
        _llm("s1", input_tokens=200, offset_ms=0),
        _llm("s2", input_tokens=600, offset_ms=100),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    ev = insights[0].evidence
    assert ev["first_input_tokens"] == 200
    assert ev["last_input_tokens"] == 600
    assert ev["total_growth"] == 400
