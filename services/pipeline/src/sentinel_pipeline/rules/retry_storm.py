from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.signals.extractor import Signals
from .base import Rule

_MIN_RETRIES = 3


class RetryStormRule(Rule):
    id       = "retry_storm"
    name     = "Retry Storm"
    severity = Severity.HIGH
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        insights: list[Insight] = []

        for span in graph.nodes.values():
            if span.retry_count >= _MIN_RETRIES and span.status.value == "error":
                insights.append(Insight(
                    workspace_id=graph.workspace_id,
                    trace_id=graph.trace_id,
                    rule_id=self.id,
                    severity=self.severity,
                    title=f"Tool '{span.name}' retried {span.retry_count} times",
                    detail=(
                        f"Span '{span.name}' ({span.kind.value}) was retried "
                        f"{span.retry_count} times with no backoff or escalation. "
                        "Repeated retries on the same input rarely succeed and "
                        "indicate a flaky tool, rate limit, or unhandled failure."
                    ),
                    recommendation=(
                        "Add exponential backoff between retries and cap at 2–3 attempts. "
                        "After the cap, escalate: fall back to an alternative tool, "
                        "raise an error, or surface the failure to the user."
                    ),
                    affected_span_ids=[span.span_id],
                    evidence={
                        "span_id":     span.span_id,
                        "span_name":   span.name,
                        "retry_count": span.retry_count,
                        "status":      span.status.value,
                    },
                ))

        return insights or None
