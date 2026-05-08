from __future__ import annotations

from collections import Counter

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Rule

# An agent must appear at least this many times in execution order to trigger
_MIN_LOOP_COUNT = 3


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
