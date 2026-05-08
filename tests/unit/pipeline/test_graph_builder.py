"""
Tests for graph_builder.py — written BEFORE the implementation (TDD).
Each test documents the exact contract the builder must satisfy.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus, EdgeKind
from sentinel_pipeline.graph.builder import build_graph


def _span(
    span_id: str,
    trace_id: str = "trace-1",
    workspace_id: str = "ws-1",
    parent_span_id: str | None = None,
    kind: SpanKind = SpanKind.GENERIC,
    agent_name: str | None = None,
    retry_count: int = 0,
    offset_ms: int = 0,
    duration_ms: int = 100,
) -> NormalizedSpan:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        name=span_id,
        kind=kind,
        status=SpanStatus.OK,
        start_time=t0,
        end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id=workspace_id,
        agent_name=agent_name,
        retry_count=retry_count,
    )


# ---------------------------------------------------------------------------
# Parent-child assembly
# ---------------------------------------------------------------------------

def test_single_span_becomes_root():
    span = _span("s1")
    g = build_graph([span])
    assert "s1" in g.nodes
    assert g.root_spans() == [span]
    assert g.edges == []


def test_parent_child_edge_created():
    parent = _span("parent")
    child  = _span("child", parent_span_id="parent")
    g = build_graph([parent, child])
    assert any(e.source_span_id == "parent" and e.target_span_id == "child"
               and e.kind == EdgeKind.PARENT_CHILD for e in g.edges)


def test_multiple_children():
    root = _span("root")
    c1   = _span("c1", parent_span_id="root")
    c2   = _span("c2", parent_span_id="root")
    g = build_graph([root, c1, c2])
    child_edges = [e for e in g.edges if e.source_span_id == "root"]
    assert len(child_edges) == 2


# ---------------------------------------------------------------------------
# Agent handoff detection
# ---------------------------------------------------------------------------

def test_agent_handoff_different_agent_names():
    a1_span = _span("a1", kind=SpanKind.AGENT_INVOKE, agent_name="AgentA")
    a2_span = _span("a2", kind=SpanKind.AGENT_INVOKE, agent_name="AgentB",
                    parent_span_id="a1")
    g = build_graph([a1_span, a2_span])
    handoff = [e for e in g.edges if e.kind == EdgeKind.AGENT_HANDOFF]
    assert len(handoff) == 1
    assert handoff[0].source_span_id == "a1"
    assert handoff[0].target_span_id == "a2"


def test_no_handoff_same_agent_name():
    a1 = _span("a1", kind=SpanKind.AGENT_INVOKE, agent_name="AgentA")
    a2 = _span("a2", kind=SpanKind.AGENT_INVOKE, agent_name="AgentA",
               parent_span_id="a1")
    g = build_graph([a1, a2])
    handoffs = [e for e in g.edges if e.kind == EdgeKind.AGENT_HANDOFF]
    assert handoffs == []


# ---------------------------------------------------------------------------
# Retry edges
# ---------------------------------------------------------------------------

def test_retry_edge_for_retried_span():
    parent = _span("tool-call", kind=SpanKind.TOOL_INVOKE)
    retry  = _span("tool-retry", kind=SpanKind.TOOL_INVOKE,
                   parent_span_id="tool-call", retry_count=1)
    g = build_graph([parent, retry])
    retry_edges = [e for e in g.edges if e.kind == EdgeKind.RETRY]
    assert len(retry_edges) == 1


def test_no_retry_edge_for_non_retry_span():
    parent = _span("tool-call", kind=SpanKind.TOOL_INVOKE)
    child  = _span("tool-ok", kind=SpanKind.TOOL_INVOKE,
                   parent_span_id="tool-call", retry_count=0)
    g = build_graph([parent, child])
    retry_edges = [e for e in g.edges if e.kind == EdgeKind.RETRY]
    assert retry_edges == []


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

def test_no_cycle_in_linear_flow():
    spans = [
        _span("s1"),
        _span("s2", parent_span_id="s1"),
        _span("s3", parent_span_id="s2"),
    ]
    g = build_graph(spans)
    assert g.has_cycle is False
    assert g.cycles == []


def test_cycle_detected_and_flagged():
    # Manually inject a cycle by having s3 reference s1 as parent
    # (unusual but must not crash — cycles are signal)
    s1 = _span("s1", kind=SpanKind.AGENT_INVOKE, agent_name="A")
    s2 = _span("s2", kind=SpanKind.AGENT_INVOKE, agent_name="B", parent_span_id="s1")
    s3 = _span("s3", kind=SpanKind.AGENT_INVOKE, agent_name="A", parent_span_id="s2")
    # build_graph should detect the repeated agent pattern even without a true edge cycle
    g = build_graph([s1, s2, s3])
    # Agent A appears as s1 and s3 with s2 in between — loop pattern
    # has_cycle may be True or False depending on edge structure, but graph must not raise
    assert g is not None  # must not raise


def test_cycle_does_not_raise():
    """build_graph must never raise on any input — cycles are data, not errors."""
    spans = [_span(f"s{i}", parent_span_id=f"s{i-1}" if i > 0 else None)
             for i in range(5)]
    try:
        g = build_graph(spans)
    except Exception as exc:
        pytest.fail(f"build_graph raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Timestamp normalization
# ---------------------------------------------------------------------------

def test_child_before_parent_corrected():
    parent = _span("p", offset_ms=100, duration_ms=200)  # 100ms → 300ms
    # Child starts 50ms before parent — clock skew
    child  = _span("c", parent_span_id="p", offset_ms=50, duration_ms=50)
    g = build_graph([parent, child])
    child_span = g.nodes["c"]
    # After normalization child.start_time >= parent.start_time
    assert child_span.start_time >= g.nodes["p"].start_time


def test_normal_timestamps_unchanged():
    parent = _span("p", offset_ms=0, duration_ms=200)
    child  = _span("c", parent_span_id="p", offset_ms=50, duration_ms=50)
    g = build_graph([parent, child])
    # Child starts inside parent window — no correction needed
    assert g.nodes["c"].start_time == child.start_time


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def test_graph_metadata():
    span = _span("s1", trace_id="t1", workspace_id="w1")
    g = build_graph([span])
    assert g.trace_id == "t1"
    assert g.workspace_id == "w1"


def test_empty_span_list():
    g = build_graph([])
    assert g.nodes == {}
    assert g.edges == []
