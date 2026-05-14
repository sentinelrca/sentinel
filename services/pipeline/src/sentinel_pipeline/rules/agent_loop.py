from __future__ import annotations

from collections import Counter

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Rule

# An agent must appear at least this many times in execution order to trigger
_MIN_LOOP_COUNT = 3

# Wrapper node names emitted by LangGraph/LangChain that are not agent nodes
_FRAMEWORK_NAMES = frozenset({
    "langgraph", "runnablesequence", "runnablelambda", "runnablewithfallbacks",
    "chatprompttemplate", "prompttemplate", "stroutputparser",
})


class AgentLoopRule(Rule):
    id       = "agent_loop"
    name     = "Agent Loop"
    severity = Severity.HIGH
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not graph.nodes:
            return None

        insights: list[Insight] = []

        # --- Path 1: Structural cycle in the graph ---
        if graph.has_cycle and self._cycle_involves_multiple_agents(graph):
            cycle_nodes  = [n for cycle in graph.cycles for n in cycle]
            agent_names  = self._agent_names_in(cycle_nodes, graph)
            loop_count   = len(cycle_nodes)
            insights.append(Insight(
                workspace_id=graph.workspace_id,
                trace_id=graph.trace_id,
                rule_id=self.id,
                severity=self.severity,
                title="Agent loop detected",
                detail=(
                    f"A cycle was detected involving {len(agent_names)} agents "
                    f"({', '.join(sorted(agent_names))}). "
                    f"The loop traversed {loop_count} spans before terminating."
                ),
                recommendation=(
                    "Add a loop counter or maximum-iteration guard at the orchestrator level. "
                    "Example: track handoff depth and raise an error or return early once a "
                    "threshold (e.g. 10) is exceeded."
                ),
                affected_span_ids=cycle_nodes,
                evidence={
                    "cycle_nodes":  cycle_nodes,
                    "loop_count":   loop_count,
                    "agent_names":  sorted(agent_names),
                },
            ))

        # --- Path 2: Same agent appears >= _MIN_LOOP_COUNT times (non-structural loop) ---
        agent_appearances = self._agent_appearance_counts(graph)
        for agent_name, count in agent_appearances.items():
            if count >= _MIN_LOOP_COUNT:
                span_ids = [
                    s.span_id for s in graph.nodes.values()
                    if s.agent_name == agent_name
                ]
                insights.append(Insight(
                    workspace_id=graph.workspace_id,
                    trace_id=graph.trace_id,
                    rule_id=self.id,
                    severity=self.severity,
                    title="Agent invoked repeatedly",
                    detail=(
                        f"Agent '{agent_name}' was invoked {count} times in a single trace. "
                        f"This often indicates a retry or delegation loop."
                    ),
                    recommendation=(
                        f"Review why '{agent_name}' is called {count} times. "
                        "If retrying, add backoff and a maximum retry limit. "
                        "If delegating, consider whether a loop exit condition is missing."
                    ),
                    affected_span_ids=span_ids,
                    evidence={
                        "agent_name":  agent_name,
                        "invocations": count,
                        "span_ids":    span_ids,
                    },
                ))

        # --- Path 3: Repeated CHAIN spans with same name (LangGraph node pattern) ---
        # LangGraph emits CHAIN spans named after graph nodes (e.g. "hermione", "harry").
        # When the same node fires 3+ times it signals a loop even without AGENT_INVOKE spans.
        if not insights:
            node_appearances = self._langgraph_node_counts(graph)
            seen_nodes: set[str] = set()
            for node_name, count in node_appearances.items():
                if count >= _MIN_LOOP_COUNT:
                    span_ids = [
                        s.span_id for s in graph.nodes.values()
                        if s.kind == SpanKind.CHAIN and s.name == node_name
                    ]
                    seen_nodes.add(node_name)
                    insights.append(Insight(
                        workspace_id=graph.workspace_id,
                        trace_id=graph.trace_id,
                        rule_id=self.id,
                        severity=self.severity,
                        title="Agent node executed repeatedly",
                        detail=(
                            f"Graph node '{node_name}' executed {count} times in a single trace. "
                            f"This pattern indicates a loop between agent nodes."
                        ),
                        recommendation=(
                            f"Add a loop counter or maximum-iteration guard. "
                            "Track handoff depth and return early once a threshold is exceeded."
                        ),
                        affected_span_ids=span_ids,
                        evidence={
                            "node_name":   node_name,
                            "invocations": count,
                            "span_ids":    span_ids,
                        },
                    ))

        return insights or None

    def _cycle_involves_multiple_agents(self, graph: FlowGraph) -> bool:
        for cycle in graph.cycles:
            agent_names = self._agent_names_in(cycle, graph)
            if len(agent_names) >= 2:
                return True
        return False

    def _agent_names_in(self, span_ids: list[str], graph: FlowGraph) -> set[str]:
        return {
            graph.nodes[sid].agent_name
            for sid in span_ids
            if sid in graph.nodes and graph.nodes[sid].agent_name
        }

    def _agent_appearance_counts(self, graph: FlowGraph) -> Counter:
        names = [
            s.agent_name
            for s in graph.nodes.values()
            if s.kind == SpanKind.AGENT_INVOKE and s.agent_name
        ]
        return Counter(names)

    def _langgraph_node_counts(self, graph: FlowGraph) -> Counter:
        """Count repeated CHAIN spans by name that have at least one LLM_CALL child.

        This identifies LangGraph agent node spans (which create CHAIN observations)
        while excluding pure routing/edge spans that have no LLM calls.
        """
        dg = graph.digraph
        names = []
        for s in graph.nodes.values():
            if s.kind != SpanKind.CHAIN:
                continue
            if not s.name or s.name.lower() in _FRAMEWORK_NAMES:
                continue
            children = [
                graph.nodes[cid]
                for cid in dg.successors(s.span_id)
                if cid in graph.nodes
            ]
            if any(c.kind == SpanKind.LLM_CALL for c in children):
                names.append(s.name)
        return Counter(names)
