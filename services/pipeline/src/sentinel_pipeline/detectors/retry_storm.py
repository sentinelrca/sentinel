from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# A single span retried this many times is considered a storm
_MIN_RETRIES_PER_SPAN = 3
# Total retries across the trace that trigger the detector
_MIN_TOTAL_RETRIES = 5


class RetryStormDetector(Detector):
    """
    Fires when a trace contains an excessive number of retries — either a single
    span retried many times or many spans each retried at least once. Retry storms
    waste tokens and latency, often masking a persistent upstream failure that
    retrying cannot fix (rate limit, auth error, broken tool).
    """

    id       = "retry_storm"
    name     = "Retry Storm"
    severity = Severity.HIGH
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not signals.retry_counts:
            return None

        total_retries = sum(signals.retry_counts.values())
        max_retries   = max(signals.retry_counts.values())

        if max_retries < _MIN_RETRIES_PER_SPAN and total_retries < _MIN_TOTAL_RETRIES:
            return None

        worst_span_id = max(signals.retry_counts, key=signals.retry_counts.__getitem__)
        worst_span    = graph.nodes.get(worst_span_id)
        worst_name    = worst_span.name if worst_span else worst_span_id

        affected = list(signals.retry_counts.keys())

        return [Insight(
            workspace_id=graph.workspace_id,
            trace_id=graph.trace_id,
            detector_id=self.id,
            severity=self.severity,
            title="Retry storm detected",
            detail=(
                f"This trace made {total_retries} retries across "
                f"{len(signals.retry_counts)} span(s). "
                f"The worst offender is '{worst_name}' with {max_retries} retries. "
                f"Excessive retries indicate a persistent failure (rate limit, auth error, "
                f"or broken dependency) that retrying cannot resolve."
            ),
            recommendation=(
                "Investigate why retries are occurring: check for rate limits, "
                "auth failures, or unreliable tool endpoints. "
                "Add exponential back-off with jitter and a circuit breaker that "
                "fails fast after a threshold rather than retrying indefinitely. "
                "Consider caching successful tool results to avoid redundant calls."
            ),
            affected_span_ids=affected,
            evidence={
                "total_retries":    total_retries,
                "spans_with_retries": len(signals.retry_counts),
                "max_retries":      max_retries,
                "worst_span_id":    worst_span_id,
                "worst_span_name":  worst_name,
            },
        )]
