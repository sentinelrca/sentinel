"""Unit tests for the retrieval_without_grounding rule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.rules.retrieval_without_grounding import RetrievalWithoutGroundingRule
from sentinel_pipeline.signals.extractor import extract_signals

rule = RetrievalWithoutGroundingRule()
_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, output_tokens=None, parent_id=None, offset_ms=0, attributes=None):
    t = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name=f"span_{span_id}", kind=kind, status=SpanStatus.OK,
        start_time=t, end_time=t + timedelta(milliseconds=100),
        workspace_id="ws1", output_tokens=output_tokens,
        attributes=attributes or {},
    )


def test_fires_when_empty_retrieval_followed_by_llm_under_same_parent():
    """RETRIEVAL returns nothing, sibling LLM_CALL fires — should trigger."""
    spans = [
        _span("root",      SpanKind.CHAIN,     offset_ms=0),
        _span("retrieval", SpanKind.RETRIEVAL,  output_tokens=0,  parent_id="root", offset_ms=10),
        _span("llm",       SpanKind.LLM_CALL,   output_tokens=100, parent_id="root", offset_ms=20),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights
    assert insights[0].rule_id == "retrieval_without_grounding"
    assert "retrieval" in insights[0].evidence["retrieval_span_id"]


def test_no_fire_when_retrieval_returns_results():
    """RETRIEVAL with output_tokens > 0 — must NOT fire."""
    spans = [
        _span("root",      SpanKind.CHAIN,    offset_ms=0),
        _span("retrieval", SpanKind.RETRIEVAL, output_tokens=80, parent_id="root", offset_ms=10),
        _span("llm",       SpanKind.LLM_CALL,  output_tokens=50, parent_id="root", offset_ms=20),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_fire_when_no_llm_follows_empty_retrieval():
    """Empty retrieval with no subsequent LLM call — agent correctly halts."""
    spans = [
        _span("root",      SpanKind.CHAIN,    offset_ms=0),
        _span("retrieval", SpanKind.RETRIEVAL, output_tokens=0, parent_id="root", offset_ms=10),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_fires_when_retrieval_result_count_is_zero_via_attribute():
    """result_count attribute = 0 should also trigger."""
    spans = [
        _span("root",      SpanKind.CHAIN,    offset_ms=0),
        _span("retrieval", SpanKind.RETRIEVAL, output_tokens=None, parent_id="root",
              offset_ms=10, attributes={"retrieval.result_count": 0}),
        _span("llm",       SpanKind.LLM_CALL,  output_tokens=50,   parent_id="root", offset_ms=20),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights


def test_no_fire_when_retrieval_output_tokens_is_none():
    """output_tokens=None means unknown, not empty — must NOT fire."""
    spans = [
        _span("root",      SpanKind.CHAIN,    offset_ms=0),
        _span("retrieval", SpanKind.RETRIEVAL, output_tokens=None, parent_id="root", offset_ms=10),
        _span("llm",       SpanKind.LLM_CALL,  output_tokens=50,   parent_id="root", offset_ms=20),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_false_positive_when_retrieval_is_root_span_without_llm_siblings():
    """Root-level retrieval with no sibling LLM calls — must NOT fire.
    Regression for the bug where parent_id=None fell back to all spans."""
    spans = [
        _span("retrieval", SpanKind.RETRIEVAL, output_tokens=0, parent_id=None, offset_ms=0),
        _span("unrelated", SpanKind.CHAIN,     parent_id=None,  offset_ms=200),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_no_false_positive_root_retrieval_with_unrelated_llm_in_separate_branch():
    """Root-level retrieval and LLM in separate branches — must NOT fire.
    Regression: old code fell back to all spans, matching unrelated LLM calls."""
    spans = [
        _span("retrieval",  SpanKind.RETRIEVAL, output_tokens=0,   parent_id=None, offset_ms=0),
        _span("rag_chain",  SpanKind.CHAIN,      parent_id=None,    offset_ms=10),
        _span("unrelated_llm", SpanKind.LLM_CALL, output_tokens=80, parent_id="rag_chain", offset_ms=20),
    ]
    graph = build_graph(spans)
    assert not rule.evaluate(graph, extract_signals(graph))


def test_fires_root_retrieval_with_sibling_root_llm():
    """Root retrieval + root LLM sibling (both parent_id=None) — should fire."""
    spans = [
        _span("retrieval", SpanKind.RETRIEVAL, output_tokens=0,  parent_id=None, offset_ms=0),
        _span("llm",       SpanKind.LLM_CALL,  output_tokens=80, parent_id=None, offset_ms=100),
    ]
    graph = build_graph(spans)
    insights = rule.evaluate(graph, extract_signals(graph))
    assert insights


def test_no_fire_on_empty_graph():
    graph = build_graph([])
    assert not rule.evaluate(graph, extract_signals(graph))
