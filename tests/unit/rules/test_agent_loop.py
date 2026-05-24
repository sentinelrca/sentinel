from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.agent_loop import AgentLoopDetector

rule = AgentLoopDetector()


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
    detector_ids = [i.detector_id for i in insights]
    assert all(d == "agent_loop" for d in detector_ids)


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


def _chain_span(span_id, name, parent_id=None, offset_ms=0):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name=name, kind=SpanKind.CHAIN, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=100),
        workspace_id="ws1",
    )


def _llm_span(span_id, parent_id, offset_ms=0):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name="ChatOpenAI", kind=SpanKind.LLM_CALL, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=50),
        workspace_id="ws1",
    )


def test_fires_on_langgraph_repeated_chain_nodes():
    """Path 3: LangGraph CHAIN nodes with same name + LLM child repeated 3× → rule fires."""
    spans = [
        _chain_span("root", "LangGraph"),
        # hermione fires 3 times, each with an LLM child
        _chain_span("h1", "hermione", parent_id="root", offset_ms=0),
        _llm_span("h1_llm", parent_id="h1", offset_ms=10),
        _chain_span("h2", "hermione", parent_id="root", offset_ms=200),
        _llm_span("h2_llm", parent_id="h2", offset_ms=210),
        _chain_span("h3", "hermione", parent_id="root", offset_ms=400),
        _llm_span("h3_llm", parent_id="h3", offset_ms=410),
    ]
    graph    = build_graph(spans)
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert insights, "Expected agent_loop insight for repeated LangGraph node"
    assert any(i.evidence.get("node_name") == "hermione" for i in insights)


def test_no_fire_on_langgraph_routing_only_chain():
    """Routing CHAIN spans (no LLM child) should not trigger the rule."""
    spans = [
        _chain_span("root", "LangGraph"),
        # "after_hermione" routing spans — no LLM children, appear 3 times
        _chain_span("r1", "after_hermione", parent_id="root", offset_ms=0),
        _chain_span("r2", "after_hermione", parent_id="root", offset_ms=100),
        _chain_span("r3", "after_hermione", parent_id="root", offset_ms=200),
    ]
    graph    = build_graph(spans)
    signals  = extract_signals(graph)
    insights = rule.evaluate(graph, signals)
    assert not insights, "Routing-only spans should not trigger agent_loop"
