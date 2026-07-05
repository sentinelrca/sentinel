from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.unused_llm_output import UnusedLlmOutputDetector

rule = UnusedLlmOutputDetector()


def _llm_span(span_id, output_text, offset_ms=0, duration_ms=1000):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id="root",
        name=span_id, kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws1",
        output_tokens=150,
        attributes={"gen_ai.output": output_text}
    )


def _tool_span(span_id, input_text, offset_ms=1050, duration_ms=500):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id="root",
        name=span_id, kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws1",
        attributes={"gen_ai.input": input_text}
    )


def _chain_span(span_id):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=None,
        name=span_id, kind=SpanKind.CHAIN, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=3000),
        workspace_id="ws1",
    )


def test_fires_when_output_unused():
    """An LLM output is generated and followed by a tool call, but never referenced."""
    root = _chain_span("root")
    llm = _llm_span("writer_llm", "This is the generated story output.", offset_ms=0)
    tool = _tool_span("log_tool", "unrelated tool input contents", offset_ms=1100)
    
    graph    = build_graph([root, llm, tool])
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    
    assert insights
    assert len(insights) == 1
    assert insights[0].detector_id == "unused_llm_output"
    assert insights[0].affected_span_ids == ["writer_llm"]


def test_no_fire_when_output_referenced():
    """An LLM output is generated and referenced by a subsequent tool call."""
    root = _chain_span("root")
    llm = _llm_span("writer_llm", "This is the generated story output.", offset_ms=0)
    tool = _tool_span("save_story_tool", "Saving: This is the generated story output.", offset_ms=1100)
    
    graph    = build_graph([root, llm, tool])
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    
    assert not insights


def test_no_fire_when_no_subsequent_spans():
    """The LLM output is generated but is the last action in the trace (returned to user)."""
    root = _chain_span("root")
    llm = _llm_span("writer_llm", "This is the final response to the user.", offset_ms=0)
    
    graph    = build_graph([root, llm])
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    
    assert not insights
