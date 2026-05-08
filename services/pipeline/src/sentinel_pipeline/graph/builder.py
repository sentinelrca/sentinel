"""
Flow graph builder.

Converts a flat list of NormalizedSpan objects (all from the same trace) into
a FlowGraph — a directed graph where nodes are spans and edges express
parent-child relationships, agent handoffs, and retries.

This is the most critical component in the pipeline. All rules depend on
correct graph construction. Key invariants:
  - Never raises on malformed input (missing parents, cycles, clock skew)
  - Cycles are flagged, never silently lost
  - Clock-skewed child spans are corrected before the graph is returned
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import networkx as nx

from sentinel_pipeline.models.span import (
    EdgeKind,
    FlowEdge,
    NormalizedSpan,
    SpanKind,
)
from sentinel_pipeline.models.graph import FlowGraph

logger = logging.getLogger(__name__)


def build_graph(spans: list[NormalizedSpan]) -> FlowGraph:
    """
    Build a FlowGraph from a list of spans belonging to the same trace.

    Handles:
    - Parent-child assembly
    - Agent handoff detection (different agent_name across AGENT_INVOKE spans)
    - Retry edges (span.retry_count > 0)
    - Cycle detection (flagged, not raised)
    - Timestamp normalization (clock skew correction)
    """
    if not spans:
        # Derive trace/workspace from nothing — return empty graph
        return FlowGraph(
            trace_id="",
            workspace_id="",
            created_at=datetime.now(timezone.utc),
        )

    trace_id     = spans[0].trace_id
    workspace_id = spans[0].workspace_id

    # Index by span_id for O(1) parent lookups
    by_id: dict[str, NormalizedSpan] = {s.span_id: s for s in spans}

    # Step 1: Timestamp normalization — correct clock-skewed children
    _normalize_timestamps(by_id)

    # Step 2: Build edges
    edges: list[FlowEdge] = []

    for span in by_id.values():
        parent = by_id.get(span.parent_span_id) if span.parent_span_id else None

        if parent is not None:
            # Always add a parent-child edge
            edges.append(FlowEdge(
                source_span_id=parent.span_id,
                target_span_id=span.span_id,
                kind=EdgeKind.PARENT_CHILD,
            ))

            # Agent handoff: both spans are agents with different names
            if (
                span.kind == SpanKind.AGENT_INVOKE
                and parent.kind == SpanKind.AGENT_INVOKE
                and span.agent_name
                and parent.agent_name
                and span.agent_name != parent.agent_name
            ):
                edges.append(FlowEdge(
                    source_span_id=parent.span_id,
                    target_span_id=span.span_id,
                    kind=EdgeKind.AGENT_HANDOFF,
                ))

            # Retry: span was a retry of its parent
            if span.retry_count > 0:
                edges.append(FlowEdge(
                    source_span_id=parent.span_id,
                    target_span_id=span.span_id,
                    kind=EdgeKind.RETRY,
                ))

    # Step 3: Construct graph
    graph = FlowGraph(
        trace_id=trace_id,
        workspace_id=workspace_id,
        created_at=datetime.now(timezone.utc),
        nodes=dict(by_id),
        edges=edges,
    )

    # Step 4: Cycle detection — uses the NetworkX DiGraph property
    _detect_cycles(graph)

    return graph


def _normalize_timestamps(by_id: dict[str, NormalizedSpan]) -> None:
    """
    Correct spans whose start_time is before their parent's start_time.

    This happens due to clock skew between services. We shift the child span
    forward so it starts exactly when its parent does. Duration is preserved.
    """
    for span in by_id.values():
        if not span.parent_span_id:
            continue
        parent = by_id.get(span.parent_span_id)
        if parent is None:
            continue
        if span.start_time < parent.start_time:
            delta = parent.start_time - span.start_time
            logger.debug(
                "Clock skew on span %s: shifted forward by %s",
                span.span_id,
                delta,
            )
            span.start_time = parent.start_time
            span.end_time   = span.end_time + delta


def _detect_cycles(graph: FlowGraph) -> None:
    """
    Detect cycles in the flow graph and record them on the FlowGraph.

    Sets graph.has_cycle = True and populates graph.cycles with the
    list of span_id sequences that form cycles.

    Never raises — cycles are a diagnostic signal, not an error.
    """
    try:
        cycle = nx.find_cycle(graph.digraph)
        # nx.find_cycle returns a list of (u, v, data) tuples
        cycle_nodes = [u for u, _v, *_ in cycle]
        graph.has_cycle = True
        graph.cycles    = [cycle_nodes]
        logger.debug("Cycle detected in trace %s: %s", graph.trace_id, cycle_nodes)
    except nx.NetworkXNoCycle:
        graph.has_cycle = False
        graph.cycles    = []
