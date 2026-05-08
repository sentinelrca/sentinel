from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.rules.agent_loop import AgentLoopRule

rule = AgentLoopRule()


def _agent_span(span_id, agent_name, parent_id=None, offset_ms=0):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name=span_id, kind=SpanKind.AGENT_INVOKE, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=100),
        workspace_id="ws1", agent_name=agent_name,
    )


def test_fires_on_repeated_agent():
    """Same agent invoked 3 times → rule fires."""
    spans = [
        _agent_span("s1", "AgentA", offset_ms=0),
        _agent_span("s2", "AgentB", parent_id="s1", offset_ms=100),
        _agent_span("s3", "AgentA", parent_id="s2", offset_ms=200),
        _agent_span("s4", "AgentB", parent_id="s3", offset_ms=300),
        _agent_span("s5", "AgentA", parent_id="s4", offset_ms=400),
    ]
    graph    = build_graph(spans)
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert insights, "Expected insights for AgentA appearing 3 times"
    rule_ids = [i.rule_id for i in insights]
    assert all(r == "agent_loop" for r in rule_ids)


def test_no_fire_on_single_agent_twice():
    """Agent appearing twice is not enough to trigger."""
    spans = [
        _agent_span("s1", "AgentA", offset_ms=0),
        _agent_span("s2", "AgentB", parent_id="s1", offset_ms=100),
        _agent_span("s3", "AgentA", parent_id="s2", offset_ms=200),
    ]
    graph    = build_graph(spans)
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert not insights, "Should not fire when agent appears only twice"


def test_no_fire_on_linear_unique_agents():
    """Linear flow with unique agents — no loop."""
    spans = [
        _agent_span("s1", "AgentA", offset_ms=0),
        _agent_span("s2", "AgentB", parent_id="s1", offset_ms=100),
        _agent_span("s3", "AgentC", parent_id="s2", offset_ms=200),
    ]
    graph    = build_graph(spans)
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert not insights


def test_insight_contains_evidence():
    """Fired insight must include agent name and invocation count in evidence."""
    spans = [
        _agent_span("s1", "AgentA", offset_ms=0),
        _agent_span("s2", "AgentB", parent_id="s1", offset_ms=100),
        _agent_span("s3", "AgentA", parent_id="s2", offset_ms=200),
        _agent_span("s4", "AgentB", parent_id="s3", offset_ms=300),
        _agent_span("s5", "AgentA", parent_id="s4", offset_ms=400),
    ]
    graph    = build_graph(spans)
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert insights
    loop_insight = next(i for i in insights if "AgentA" in str(i.evidence))
    assert loop_insight.evidence["invocations"] == 3
    assert loop_insight.evidence["agent_name"] == "AgentA"
