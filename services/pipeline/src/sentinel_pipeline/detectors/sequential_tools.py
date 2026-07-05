from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# Minimum saving (ms) before the detector fires — avoids noise on fast tools
_MIN_SAVED_MS: float = 500.0


class SequentialToolsDetector(Detector):
    id = "sequential_tools"
    name = "Sequential Tool Calls"
    severity = Severity.WARNING
    tier = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not signals.sequential_tool_pairs:
            return None

        insights: list[Insight] = []
        for pair in signals.sequential_tool_pairs:
            if pair.saved_ms < _MIN_SAVED_MS:
                continue
            insights.append(
                Insight(
                    workspace_id=graph.workspace_id,
                    trace_id=graph.trace_id,
                    detector_id=self.id,
                    severity=self.severity,
                    title="Sequential tool calls can be parallelised",
                    detail=(
                        f"Tools '{pair.tool_a}' and '{pair.tool_b}' share the same parent "
                        f"and have no data dependency between them, but are executed serially. "
                        f"Running them in parallel would save approximately {pair.saved_ms:.0f}ms."
                    ),
                    recommendation=(
                        f"Wrap '{pair.tool_a}' and '{pair.tool_b}' in an async gather or "
                        "parallel node in your agent framework. "
                        "Example (LangGraph): use a fan-out edge to both tools from the same node."
                    ),
                    affected_span_ids=[pair.span_id_a, pair.span_id_b],
                    evidence={
                        "tool_a": pair.tool_a,
                        "tool_b": pair.tool_b,
                        "saved_ms": pair.saved_ms,
                        "span_id_a": pair.span_id_a,
                        "span_id_b": pair.span_id_b,
                    },
                )
            )

        return insights or None
