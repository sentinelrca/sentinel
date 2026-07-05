from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import networkx as nx

from .span import NormalizedSpan, FlowEdge


@dataclass
class FlowGraph:
    trace_id: str
    workspace_id: str
    created_at: datetime

    # span_id → NormalizedSpan
    nodes: dict[str, NormalizedSpan] = field(default_factory=dict)
    edges: list[FlowEdge] = field(default_factory=list)

    # Cycle metadata — populated by graph_builder if a cycle is detected
    has_cycle: bool = False
    cycles: list[list[str]] = field(default_factory=list)  # each cycle = list of span_ids

    # Backing NetworkX DiGraph — built lazily or by graph_builder
    _digraph: nx.DiGraph | None = field(default=None, repr=False, compare=False)

    @property
    def digraph(self) -> nx.DiGraph:
        if self._digraph is None:
            self._digraph = self._build_digraph()
        return self._digraph

    def _build_digraph(self) -> nx.DiGraph:
        g = nx.DiGraph()
        for span_id, span in self.nodes.items():
            g.add_node(span_id, span=span)
        for edge in self.edges:
            g.add_edge(edge.source_span_id, edge.target_span_id, kind=edge.kind)
        return g

    def invalidate_digraph(self) -> None:
        """Call after modifying nodes/edges to force digraph rebuild."""
        self._digraph = None

    def span(self, span_id: str) -> NormalizedSpan:
        return self.nodes[span_id]

    def root_spans(self) -> list[NormalizedSpan]:
        return [s for s in self.nodes.values() if s.is_root()]

    def agent_names(self) -> set[str]:
        return {s.agent_name for s in self.nodes.values() if s.agent_name}

    def span_count(self) -> int:
        return len(self.nodes)
