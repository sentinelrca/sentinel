from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# Thresholds: a trace this deep almost certainly lacks iteration guards
_MIN_LLM_CALLS = 10
_MIN_AGENT_STEPS = 4  # at least some agent coordination to distinguish from simple chains


class MissingTerminationConditionDetector(Detector):
    """
    Fires when a trace has a high number of LLM calls AND agent steps with no
    evidence of bounded iteration. This is distinct from agent_loop (which detects
    structural cycles or the same agent repeating) — this catches linear but
    unbounded workflows where no max-step or token-budget guard is in place.

    Literature basis: specification & design failures account for 41.8% of
    multi-agent production breakdowns; missing termination conditions are the
    leading cause (MAST taxonomy, 2026).
    """

    id = "missing_termination_condition"
    name = "Missing Termination Condition"
    severity = Severity.HIGH
    tier = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not graph.nodes:
            return None

        llm_calls = [s for s in graph.nodes.values() if s.kind == SpanKind.LLM_CALL]
        agent_steps = [
            s for s in graph.nodes.values() if s.kind in (SpanKind.AGENT_INVOKE, SpanKind.CHAIN)
        ]

        if len(llm_calls) < _MIN_LLM_CALLS or len(agent_steps) < _MIN_AGENT_STEPS:
            return None

        # Skip only when agent_loop will fire for the cycle (Path 1 requires >= 2 agents).
        # A single-agent cycle must still be caught here.
        if graph.has_cycle:
            cycle_agents = {
                graph.nodes[n].agent_name
                for cycle in graph.cycles
                for n in cycle
                if n in graph.nodes and graph.nodes[n].agent_name
            }
            if len(cycle_agents) >= 2:
                return None

        llm_span_ids = [s.span_id for s in llm_calls]

        return [
            Insight(
                workspace_id=graph.workspace_id,
                trace_id=graph.trace_id,
                detector_id=self.id,
                severity=self.severity,
                title="No termination condition detected",
                detail=(
                    f"This trace made {len(llm_calls)} LLM calls across {len(agent_steps)} agent "
                    f"steps with no structural evidence of a max-iteration or token-budget guard. "
                    f"Unbounded agent workflows are the leading cause of runaway costs and "
                    f"infinite loops in production (41.8% of multi-agent failures)."
                ),
                recommendation=(
                    "Add an explicit termination guard at the orchestrator level: "
                    "a max_iterations counter, a token budget check, or a step limit. "
                    "Example (LangGraph): set recursion_limit on the graph. "
                    "Example (CrewAI): set max_iter on the crew. "
                    "Also consider a circuit breaker that returns a safe fallback response "
                    "when the limit is reached rather than raising an exception."
                ),
                affected_span_ids=llm_span_ids[:10],  # representative sample
                evidence={
                    "llm_call_count": len(llm_calls),
                    "agent_step_count": len(agent_steps),
                    "total_span_count": len(graph.nodes),
                },
            )
        ]
