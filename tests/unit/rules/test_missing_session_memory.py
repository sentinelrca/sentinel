"""Unit tests for the missing_session_memory rule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.rules.missing_session_memory import MissingSessionMemoryRule
from sentinel_pipeline.signals.extractor import extract_signals

rule = MissingSessionMemoryRule()
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _llm(span_id, input_tokens, offset_ms=0):
    t = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name="ChatOpenAI", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t, end_time=t + timedelta(milliseconds=50),
        workspace_id="ws1", input_tokens=input_tokens,
    )


def _tool(span_id, name, offset_ms=0):
    t = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=name, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t, end_time=t + timedelta(milliseconds=20),
        workspace_id="ws1",
    )


def test_fires_when_3_llm_calls_with_growing_tokens_and_no_memory_tool():
    """100 → 120 → 160 tokens (1.6× growth, ≥1.5 threshold) with no memory tool."""
    spans = [
        _llm("s1", input_tokens=100, offset_ms=0),
        _llm("s2", input_tokens=120, offset_ms=100),
        _llm("s3", input_tokens=160, offset_ms=200),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert insights[0].rule_id == "missing_session_memory"
    assert insights[0].evidence["memory_tools_found"] is False


def test_no_fire_when_memory_tool_present():
    """Same token growth but a 'store_memory' tool exists — rule must NOT fire."""
    spans = [
        _llm("s1",  input_tokens=100, offset_ms=0),
        _llm("s2",  input_tokens=120, offset_ms=100),
        _llm("s3",  input_tokens=160, offset_ms=200),
        _tool("m1", name="store_memory", offset_ms=50),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_when_tokens_not_growing_enough():
    """Growth ratio < 1.5 — must NOT fire."""
    spans = [
        _llm("s1", input_tokens=100, offset_ms=0),
        _llm("s2", input_tokens=110, offset_ms=100),
        _llm("s3", input_tokens=140, offset_ms=200),  # 1.4× — below threshold
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_with_fewer_than_3_llm_calls():
    spans = [
        _llm("s1", input_tokens=100, offset_ms=0),
        _llm("s2", input_tokens=200, offset_ms=100),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_on_empty_graph():
    graph = build_graph([])
    assert not rule.evaluate(graph, extract_signals(graph))


def test_memory_tool_patterns_all_suppress_rule():
    """All memory tool name patterns should suppress the rule."""
    memory_tool_names = ["retrieve_memory", "recall_facts", "zep_search",
                         "remember_user", "history_lookup", "summary_store"]
    for tool_name in memory_tool_names:
        spans = [
            _llm("s1", input_tokens=100, offset_ms=0),
            _llm("s2", input_tokens=120, offset_ms=100),
            _llm("s3", input_tokens=160, offset_ms=200),
            _tool("m1", name=tool_name, offset_ms=50),
        ]
        graph = build_graph(spans)
        assert not rule.evaluate(graph, extract_signals(graph)), \
            f"Rule should not fire when memory tool '{tool_name}' is present"


def test_unrelated_tool_does_not_suppress_rule():
    """A tool named 'search_web' is not a memory tool — rule should still fire."""
    spans = [
        _llm("s1",  input_tokens=100, offset_ms=0),
        _llm("s2",  input_tokens=120, offset_ms=100),
        _llm("s3",  input_tokens=160, offset_ms=200),
        _tool("t1", name="search_web", offset_ms=50),
    ]
    graph = build_graph(spans)
    assert rule.evaluate(graph, extract_signals(graph))


def test_evidence_contains_growth_details():
    spans = [
        _llm("s1", input_tokens=100, offset_ms=0),
        _llm("s2", input_tokens=130, offset_ms=100),
        _llm("s3", input_tokens=180, offset_ms=200),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    ev = insights[0].evidence
    assert ev["first_input_tokens"] == 100
    assert ev["last_input_tokens"] == 180
    assert ev["llm_call_count"] == 3
    assert ev["growth_ratio"] == 1.8


def test_fires_exactly_at_growth_threshold():
    """Exactly 1.5× growth should fire."""
    spans = [
        _llm("s1", input_tokens=100, offset_ms=0),
        _llm("s2", input_tokens=120, offset_ms=100),
        _llm("s3", input_tokens=150, offset_ms=200),  # exactly 1.5×
    ]
    graph = build_graph(spans)
    assert rule.evaluate(graph, extract_signals(graph))
