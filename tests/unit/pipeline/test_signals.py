from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.signals.extractor import extract_signals

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, parent_id=None, offset_ms=0, duration_ms=500,
          input_tokens=0, output_tokens=0, retry_count=0, name=None, agent_name=None):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="t1", parent_span_id=parent_id,
        name=name or span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws1",
        input_tokens=input_tokens, output_tokens=output_tokens,
        retry_count=retry_count,
        agent_name=agent_name or "",
    )


# ── Token aggregation ────────────────────────────────────────────────────────

def test_token_totals():
    spans = [
        _span("s1", SpanKind.LLM_CALL, input_tokens=100, output_tokens=50),
        _span("s2", SpanKind.LLM_CALL, parent_id="s1", offset_ms=500,
              input_tokens=200, output_tokens=80),
    ]
    signals = extract_signals(build_graph(spans))
    assert signals.total_input_tokens == 300
    assert signals.total_output_tokens == 130


def test_zero_tokens_when_no_llm_spans():
    spans = [_span("s1", SpanKind.TOOL_INVOKE)]
    signals = extract_signals(build_graph(spans))
    assert signals.total_input_tokens == 0
    assert signals.total_output_tokens == 0


# ── Retry counts ─────────────────────────────────────────────────────────────

def test_retry_counts_collected():
    spans = [
        _span("s1", SpanKind.LLM_CALL, retry_count=2),
        _span("s2", SpanKind.LLM_CALL, parent_id="s1", offset_ms=500, retry_count=0),
    ]
    signals = extract_signals(build_graph(spans))
    assert "s1" in signals.retry_counts
    assert signals.retry_counts["s1"] == 2
    assert "s2" not in signals.retry_counts


def test_no_retries_when_none_present():
    spans = [_span("s1", SpanKind.CHAIN)]
    signals = extract_signals(build_graph(spans))
    assert signals.retry_counts == {}


# ── Critical path ─────────────────────────────────────────────────────────────

def test_critical_path_linear_chain():
    """Linear A→B→C: critical path = sum of all durations."""
    spans = [
        _span("a", SpanKind.CHAIN, duration_ms=100),
        _span("b", SpanKind.LLM_CALL, parent_id="a", offset_ms=100, duration_ms=200),
        _span("c", SpanKind.TOOL_INVOKE, parent_id="b", offset_ms=300, duration_ms=150),
    ]
    signals = extract_signals(build_graph(spans))
    assert signals.critical_path_ms == 450


def test_critical_path_zero_for_cyclic_graph():
    """Cyclic graphs cannot compute DAG longest path — must return 0."""
    spans = [
        _span("a", SpanKind.AGENT_INVOKE, agent_name="AgentA"),
        _span("b", SpanKind.AGENT_INVOKE, parent_id="a", offset_ms=100, agent_name="AgentB"),
        _span("c", SpanKind.AGENT_INVOKE, parent_id="b", offset_ms=200, agent_name="AgentA"),
    ]
    graph = build_graph(spans)
    # Force a cycle flag (builder may not auto-detect without explicit cycle edges)
    graph.has_cycle = True
    from sentinel_pipeline.signals.extractor import extract_signals as _ex
    signals = _ex(graph)
    assert signals.critical_path_ms == 0.0


def test_empty_graph_returns_zero_signals():
    signals = extract_signals(build_graph([]))
    assert signals.critical_path_ms == 0.0
    assert signals.total_input_tokens == 0
    assert signals.total_output_tokens == 0
    assert signals.sequential_tool_pairs == []


# ── Sequential tool pairs ─────────────────────────────────────────────────────

def test_sequential_tool_pair_detected():
    """Two serial sibling tools → one sequential pair."""
    root = _span("root", SpanKind.CHAIN, duration_ms=3000)
    a = _span("a", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=0, duration_ms=1000, name="search")
    b = _span("b", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=1000, duration_ms=1000, name="fetch")
    signals = extract_signals(build_graph([root, a, b]))
    assert len(signals.sequential_tool_pairs) == 1
    pair = signals.sequential_tool_pairs[0]
    assert pair.tool_a == "search"
    assert pair.tool_b == "fetch"
    assert pair.saved_ms == 1000  # b's full duration


def test_overlapping_tools_not_sequential():
    """Overlapping tools are not a sequential pair."""
    root = _span("root", SpanKind.CHAIN, duration_ms=2000)
    a = _span("a", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=0, duration_ms=1000)
    b = _span("b", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=500, duration_ms=1000)
    signals = extract_signals(build_graph([root, a, b]))
    assert signals.sequential_tool_pairs == []


def test_single_tool_no_pair():
    root = _span("root", SpanKind.CHAIN)
    a = _span("a", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=0, duration_ms=500)
    signals = extract_signals(build_graph([root, a]))
    assert signals.sequential_tool_pairs == []


def test_three_serial_tools_produces_two_pairs():
    """A→B→C serial: pairs (A,B) and (B,C)."""
    root = _span("root", SpanKind.CHAIN, duration_ms=4000)
    a = _span("a", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=0,    duration_ms=1000, name="t1")
    b = _span("b", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=1000, duration_ms=1000, name="t2")
    c = _span("c", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=2000, duration_ms=1000, name="t3")
    signals = extract_signals(build_graph([root, a, b, c]))
    assert len(signals.sequential_tool_pairs) == 2


# ── Loop nodes ────────────────────────────────────────────────────────────────

def test_loop_nodes_populated_when_cycle_present():
    spans = [
        _span("a", SpanKind.AGENT_INVOKE, agent_name="AgentA"),
        _span("b", SpanKind.AGENT_INVOKE, parent_id="a", offset_ms=100, agent_name="AgentB"),
    ]
    graph = build_graph(spans)
    graph.has_cycle = True
    graph.cycles = [["a", "b"]]
    signals = extract_signals(graph)
    assert "a" in signals.loop_nodes
    assert "b" in signals.loop_nodes


def test_loop_nodes_empty_without_cycle():
    spans = [_span("a", SpanKind.CHAIN)]
    signals = extract_signals(build_graph(spans))
    assert signals.loop_nodes == []
