from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors.missing_termination_condition import (
    MissingTerminationConditionDetector,
    _MIN_LLM_CALLS,
    _MIN_AGENT_STEPS,
)

detector = MissingTerminationConditionDetector()

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, agent_name=None, parent_id=None, offset_ms=0):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1",
        parent_span_id=parent_id,
        name=span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=300),
        workspace_id="ws1",
        agent_name=agent_name,
    )


def _llm(span_id, agent_name=None, offset_ms=0):
    return _span(span_id, SpanKind.LLM_CALL, agent_name=agent_name, offset_ms=offset_ms)


def _agent(span_id, agent_name=None, parent_id=None, offset_ms=0):
    return _span(span_id, SpanKind.AGENT_INVOKE, agent_name=agent_name,
                 parent_id=parent_id, offset_ms=offset_ms)


def _chain(span_id, parent_id=None, offset_ms=0):
    return _span(span_id, SpanKind.CHAIN, parent_id=parent_id, offset_ms=offset_ms)


def _unbounded_trace(llm_count=_MIN_LLM_CALLS, agent_count=_MIN_AGENT_STEPS):
    """Build a trace with enough LLM calls and agent steps to trigger the detector."""
    spans = []
    for i in range(llm_count):
        spans.append(_llm(f"llm_{i}", offset_ms=i * 100))
    for i in range(agent_count):
        spans.append(_agent(f"agent_{i}", agent_name="orchestrator", offset_ms=i * 150))
    return spans


# ---------------------------------------------------------------------------
# Should fire
# ---------------------------------------------------------------------------

def test_fires_when_above_both_thresholds():
    spans = _unbounded_trace()
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Expected insight for trace with no termination guard"
    assert insights[0].detector_id == "missing_termination_condition"
    ev = insights[0].evidence
    assert ev["llm_call_count"] == _MIN_LLM_CALLS
    assert ev["agent_step_count"] == _MIN_AGENT_STEPS


def test_fires_with_chain_spans_counting_as_agent_steps():
    """CHAIN spans count toward agent_step_count."""
    spans = [_llm(f"llm_{i}", offset_ms=i * 100) for i in range(_MIN_LLM_CALLS)]
    spans += [_chain(f"chain_{i}", offset_ms=i * 150) for i in range(_MIN_AGENT_STEPS)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights


def test_fires_on_single_agent_cycle():
    """One agent repeating itself (no second agent) must still fire — agent_loop skips this."""
    spans = [_agent("agent_a", agent_name="solo", offset_ms=0)]
    spans += [_llm(f"llm_{i}", offset_ms=(i + 1) * 100) for i in range(_MIN_LLM_CALLS)]
    spans += [_agent(f"step_{i}", agent_name="solo", offset_ms=(i + 20) * 100)
              for i in range(_MIN_AGENT_STEPS - 1)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights, "Single-agent cycle should trigger missing_termination_condition"


def test_evidence_has_correct_fields():
    spans = _unbounded_trace(llm_count=15, agent_count=6)
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    ev = insights[0].evidence
    assert ev["llm_call_count"] == 15
    assert ev["agent_step_count"] == 6
    assert "total_span_count" in ev
    assert insights[0].severity.value == "high"


def test_affected_span_ids_are_llm_spans():
    spans = _unbounded_trace()
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = detector.evaluate(graph, signals)
    assert insights
    # All affected spans should be LLM_CALL spans
    for sid in insights[0].affected_span_ids:
        assert graph.nodes[sid].kind == SpanKind.LLM_CALL


# ---------------------------------------------------------------------------
# Should not fire
# ---------------------------------------------------------------------------

def test_no_fire_when_llm_calls_below_threshold():
    spans = _unbounded_trace(llm_count=_MIN_LLM_CALLS - 1)
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_when_agent_steps_below_threshold():
    spans = _unbounded_trace(agent_count=_MIN_AGENT_STEPS - 1)
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_on_empty_graph():
    graph = build_graph([])
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)


def test_no_fire_when_multi_agent_cycle_present():
    """If a cycle spans ≥2 distinct agents, agent_loop fires instead — skip here.

    Real traces don't produce graph cycles (each span has one parent forming a
    DAG), so we patch graph.has_cycle / graph.cycles to simulate the condition.
    """
    from unittest.mock import patch

    spans = _unbounded_trace()
    graph = build_graph(spans)
    signals = extract_signals(graph)

    # Cycle involving two distinct agents — detector must defer to agent_loop
    cycle_node_ids = [s.span_id for s in spans if s.kind.value == "agent_invoke"][:2]
    with (
        patch.object(graph, "has_cycle", True),
        patch.object(graph, "cycles", [cycle_node_ids]),
    ):
        # Patch graph.nodes so the cycle nodes have distinct agent_names
        graph.nodes[cycle_node_ids[0]].agent_name = "hermione"
        graph.nodes[cycle_node_ids[1]].agent_name = "harry"
        result = detector.evaluate(graph, signals)

    assert result is None, "Should not fire when agent_loop will handle the multi-agent cycle"


def test_no_fire_simple_chain_no_agent_steps():
    """A simple LLM chain with no agent coordination should not fire."""
    spans = [_llm(f"llm_{i}", offset_ms=i * 100) for i in range(_MIN_LLM_CALLS)]
    graph = build_graph(spans)
    signals = extract_signals(graph)
    assert not detector.evaluate(graph, signals)
