from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Rule

_SPIKE_THRESHOLD = 0.50  # span must be >50 % of total trace duration


class LatencySpikeRule(Rule):
    id       = "latency_spike"
    name     = "Latency Spike"
    severity = Severity.WARNING
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not graph.nodes:
            return None

        all_spans = list(graph.nodes.values())
        if not all_spans:
            return None

        # Total trace duration = wall-clock from earliest start to latest end
        min_start = min(s.start_time for s in all_spans)
        max_end   = max(s.end_time   for s in all_spans)
        total_ms  = (max_end - min_start).total_seconds() * 1000

        if total_ms <= 0:
            return None

        insights: list[Insight] = []
        for span in all_spans:
            frac = span.duration_ms / total_ms
            if frac > _SPIKE_THRESHOLD:
                pct = round(frac * 100, 1)
                insights.append(Insight(
                    workspace_id=graph.workspace_id,
                    trace_id=graph.trace_id,
                    rule_id=self.id,
                    severity=self.severity,
                    title=f"Latency spike in '{span.name}'",
                    detail=(
                        f"Span '{span.name}' ({span.kind.value}) consumed {pct}% of total "
                        f"trace duration ({span.duration_ms:.0f} ms out of {total_ms:.0f} ms). "
                        "This single span is the dominant cost of the trace."
                    ),
                    recommendation=(
                        f"Profile '{span.name}' to find the bottleneck. "
                        "If it's a tool call, consider caching, parallelising with other "
                        "independent spans, or moving it to the critical path only when needed."
                    ),
                    affected_span_ids=[span.span_id],
                    evidence={
                        "span_id":      span.span_id,
                        "span_name":    span.name,
                        "duration_ms":  round(span.duration_ms),
                        "total_ms":     round(total_ms),
                        "fraction_pct": pct,
                    },
                ))

        return insights or None
