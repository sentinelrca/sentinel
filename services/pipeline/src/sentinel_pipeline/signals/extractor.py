"""
Signal extraction from a FlowGraph.

Computes derived metrics used by the rule engine. All rules receive
a Signals object rather than querying the graph directly for performance.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.span import SpanKind


@dataclass
class SequentialToolPair:
    span_id_a:  str
    span_id_b:  str
    tool_a:     str
    tool_b:     str
    saved_ms:   float  # time that would be saved by parallelising


@dataclass
class Signals:
    # Latency
    critical_path_ms:       float = 0.0
    total_duration_ms:      float = 0.0

    # Tokens
    total_input_tokens:     int = 0
    total_output_tokens:    int = 0

    # Retries
    retry_counts:           dict[str, int] = field(default_factory=dict)
    # span_id → retry_count for spans where retry_count > 0

    # Parallelisation opportunities
    sequential_tool_pairs:  list[SequentialToolPair] = field(default_factory=list)

    # Loop signals
    loop_nodes:             list[str] = field(default_factory=list)
    # span_ids involved in detected cycles


def extract_signals(graph: FlowGraph) -> Signals:
    """Compute all signals from a FlowGraph in a single pass."""
    signals = Signals()

    if not graph.nodes:
        return signals

    # --- Token aggregation & retry counts ---
    for span in graph.nodes.values():
        if span.input_tokens:
            signals.total_input_tokens  += span.input_tokens
        if span.output_tokens:
            signals.total_output_tokens += span.output_tokens
        if span.retry_count > 0:
            signals.retry_counts[span.span_id] = span.retry_count

    # --- Total flow duration (root span end - root span start) ---
    roots = graph.root_spans()
    if roots:
        earliest = min(s.start_time for s in roots)
        latest   = max(s.end_time   for s in graph.nodes.values())
        signals.total_duration_ms = (latest - earliest).total_seconds() * 1000

    # --- Critical path (longest weighted path in DAG) ---
    signals.critical_path_ms = _critical_path_ms(graph)

    # --- Sequential tool pairs ---
    signals.sequential_tool_pairs = _find_sequential_tools(graph)

    # --- Loop nodes from cycle detection ---
    if graph.has_cycle:
        signals.loop_nodes = [node for cycle in graph.cycles for node in cycle]

    return signals


def _critical_path_ms(graph: FlowGraph) -> float:
    """
    Return the duration of the longest path through the flow graph (in ms).

    For cyclic graphs we fall back to total_duration_ms as an approximation
    since DAG longest-path algorithms require acyclicity.
    """
    if graph.has_cycle:
        # Cannot compute DAG longest path on a cyclic graph
        return 0.0

    g = graph.digraph
    if g.number_of_nodes() == 0:
        return 0.0

    # Weight each edge by the duration of the TARGET span
    for node_id in g.nodes:
        span = graph.nodes.get(node_id)
        g.nodes[node_id]["weight"] = span.duration_ms if span else 0.0

    try:
        path = nx.dag_longest_path(g, weight="weight")
        return sum(graph.nodes[n].duration_ms for n in path if n in graph.nodes)
    except Exception:
        return 0.0


def _find_sequential_tools(graph: FlowGraph) -> list[SequentialToolPair]:
    """
    Identify TOOL_INVOKE spans that share the same parent, have no data
    dependency between them, but are executed serially (one ends before
    the next starts). These are parallelisation opportunities.
    """
    pairs: list[SequentialToolPair] = []

    # Group tool spans by parent
    parent_to_tools: dict[str | None, list] = {}
    for span in graph.nodes.values():
        if span.kind == SpanKind.TOOL_INVOKE:
            parent_to_tools.setdefault(span.parent_span_id, []).append(span)

    for sibling_tools in parent_to_tools.values():
        if len(sibling_tools) < 2:
            continue

        # Sort by start time
        sibling_tools.sort(key=lambda s: s.start_time)

        for i in range(len(sibling_tools) - 1):
            a = sibling_tools[i]
            b = sibling_tools[i + 1]

            # Check for data dependency: does b's input reference a's output?
            # Simple heuristic: if b starts after a ends → serial, no overlap
            if b.start_time >= a.end_time:
                saved_ms = (b.start_time - a.end_time).total_seconds() * 1000
                # The saving is b's full duration (it could have run in parallel)
                parallel_saving = b.duration_ms
                pairs.append(SequentialToolPair(
                    span_id_a=a.span_id,
                    span_id_b=b.span_id,
                    tool_a=a.name,
                    tool_b=b.name,
                    saved_ms=parallel_saving,
                ))

    return pairs
