from __future__ import annotations

import statistics

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# --- Tunable thresholds (see M3+ for per-workspace config) ---
_CONTEXT_UTILIZATION_THRESHOLD = 0.75   # flag when input_tokens > 75% of model context window
_LOW_THROUGHPUT_MULTIPLIER     = 3.0    # flag when tok/s is < median / 3 among same-model peers
_CRITICAL_PATH_THRESHOLD       = 0.60   # flag when a single LLM span > 60% of total trace time
_MIN_PEERS_FOR_THROUGHPUT      = 2      # need at least this many other same-model spans to compare

# Known model context window sizes (tokens).
# Prefix-matched so "gpt-4o-2024-11-20" matches "gpt-4o".
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "o3":                      200_000,
    "o1":                      128_000,
    "o1-mini":                 128_000,
    "gpt-4-32k":                32_768,
    "gpt-4o":                  128_000,
    "gpt-4":                     8_192,
    "gpt-3.5-turbo":            16_385,
    "claude-3-5-sonnet":       200_000,
    "claude-3-5-haiku":        200_000,
    "claude-3-opus":           200_000,
    "claude-3-sonnet":         200_000,
    "claude-3-haiku":          200_000,
    "claude-opus-4":           200_000,
    "claude-sonnet-4":         200_000,
    "claude-haiku-4":          200_000,
    "gemini-2.0-flash":      1_048_576,
    "gemini-1.5-pro":        1_048_576,
    "gemini-1.5-flash":      1_048_576,
    "gemini-1.0-pro":           32_768,
}


def _context_window(model: str) -> int | None:
    """Return context window size for a model, using longest prefix match."""
    if not model:
        return None
    m = model.lower()
    # Sort by key length descending so longer/more-specific prefixes match first
    for known, size in sorted(_MODEL_CONTEXT_WINDOWS.items(), key=lambda x: -len(x[0])):
        if m.startswith(known.lower()):
            return size
    return None


def _throughput(span: NormalizedSpan) -> float | None:
    """Tokens per second for an LLM span. None if output_tokens unavailable."""
    if not span.output_tokens or span.duration_ms <= 0:
        return None
    return (span.output_tokens / span.duration_ms) * 1000  # tok/s


class LatencySpikeDetector(Detector):
    """
    Detects abnormally high latency on LLM calls. Fires separately for each
    root cause identified:

      low_throughput         — one call is far slower (tok/s) than same-model
                               peers in the same trace; likely API throttling,
                               rate limiting, or a cold start.

      oversized_context      — input tokens exceed a high fraction of the
                               model's context window; inference slows sharply
                               as context fills.

      critical_path_bottleneck — a single LLM span dominates total trace time;
                               it is the primary latency lever regardless of cause.

    Tool/MCP latency analysis requires per-tool historical baselines and is
    deferred to the commercial tier (M3+).
    """

    id       = "latency_spike"
    name     = "Latency Spike"
    severity = Severity.WARNING
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        llm_spans = [s for s in graph.nodes.values() if s.kind == SpanKind.LLM_CALL]
        if not llm_spans:
            return None

        insights: list[Insight] = []
        insights.extend(self._check_low_throughput(graph, llm_spans))
        insights.extend(self._check_oversized_context(graph, llm_spans))
        insights.extend(self._check_critical_path(graph, signals, llm_spans))
        return insights or None

    # ------------------------------------------------------------------

    def _check_low_throughput(
        self, graph: FlowGraph, llm_spans: list[NormalizedSpan]
    ) -> list[Insight]:
        # Group by model, keep only spans that have output_tokens
        by_model: dict[str, list[NormalizedSpan]] = {}
        for span in llm_spans:
            model = span.model or "unknown"
            if _throughput(span) is not None:
                by_model.setdefault(model, []).append(span)

        insights: list[Insight] = []
        for model, peers in by_model.items():
            if len(peers) < _MIN_PEERS_FOR_THROUGHPUT + 1:
                continue  # need enough peers for a meaningful median

            rates = [_throughput(s) for s in peers]  # all non-None by construction
            median_rate = statistics.median(rates)
            if median_rate <= 0:
                continue

            threshold = median_rate / _LOW_THROUGHPUT_MULTIPLIER
            for span, rate in zip(peers, rates):
                if rate < threshold:
                    slowdown = median_rate / rate
                    insights.append(Insight(
                        workspace_id=graph.workspace_id,
                        trace_id=graph.trace_id,
                        detector_id=self.id,
                        severity=self.severity,
                        title=f"Low throughput on {model} call",
                        detail=(
                            f"LLM call '{span.name}' using {model} completed in "
                            f"{span.duration_ms:.0f}ms generating {span.output_tokens} tokens "
                            f"({rate:.1f} tok/s). The median for {model} in this trace is "
                            f"{median_rate:.1f} tok/s — {slowdown:.1f}× slower than peers. "
                            f"Likely causes: API rate limiting, cold start, or network congestion."
                        ),
                        recommendation=(
                            "Check API rate limit headers and error logs for this call. "
                            "If it occurs on the first call, consider warming the connection. "
                            "Add retry with exponential back-off for transient throttling. "
                            "If persistent, evaluate switching to a lower-latency endpoint or region."
                        ),
                        affected_span_ids=[span.span_id],
                        evidence={
                            "model":            model,
                            "throughput_toks":  round(rate, 2),
                            "median_toks":      round(median_rate, 2),
                            "slowdown_factor":  round(slowdown, 2),
                            "duration_ms":      span.duration_ms,
                            "output_tokens":    span.output_tokens,
                        },
                    ))
        return insights

    def _check_oversized_context(
        self, graph: FlowGraph, llm_spans: list[NormalizedSpan]
    ) -> list[Insight]:
        insights: list[Insight] = []
        for span in llm_spans:
            if not span.input_tokens or not span.model:
                continue
            window = _context_window(span.model)
            if window is None:
                continue
            utilization = span.input_tokens / window
            if utilization < _CONTEXT_UTILIZATION_THRESHOLD:
                continue
            insights.append(Insight(
                workspace_id=graph.workspace_id,
                trace_id=graph.trace_id,
                detector_id=self.id,
                severity=self.severity,
                title=f"Oversized context on {span.model} call",
                detail=(
                    f"LLM call '{span.name}' sent {span.input_tokens:,} input tokens to "
                    f"{span.model} ({utilization:.0%} of its {window:,}-token context window). "
                    f"Inference latency scales with context length; at this utilization "
                    f"both latency and cost increase sharply."
                ),
                recommendation=(
                    "Reduce prompt size by summarising conversation history, using RAG to "
                    "retrieve only relevant chunks, or truncating older turns. "
                    "If large context is unavoidable, consider a model with a larger window "
                    "that handles long contexts more efficiently (e.g. Gemini 1.5 Pro, Claude)."
                ),
                affected_span_ids=[span.span_id],
                evidence={
                    "model":         span.model,
                    "input_tokens":  span.input_tokens,
                    "context_window": window,
                    "utilization":   round(utilization, 3),
                },
            ))
        return insights

    def _check_critical_path(
        self,
        graph: FlowGraph,
        signals: Signals,
        llm_spans: list[NormalizedSpan],
    ) -> list[Insight]:
        if signals.total_duration_ms <= 0:
            return []
        insights: list[Insight] = []
        for span in llm_spans:
            ratio = span.duration_ms / signals.total_duration_ms
            if ratio < _CRITICAL_PATH_THRESHOLD:
                continue
            insights.append(Insight(
                workspace_id=graph.workspace_id,
                trace_id=graph.trace_id,
                detector_id=self.id,
                severity=Severity.HIGH,
                title="LLM call dominates trace latency",
                detail=(
                    f"LLM call '{span.name}'"
                    + (f" ({span.model})" if span.model else "")
                    + f" took {span.duration_ms:.0f}ms — {ratio:.0%} of the total "
                    f"trace duration of {signals.total_duration_ms:.0f}ms. "
                    f"Optimising this single call is the highest-leverage latency improvement."
                ),
                recommendation=(
                    "Consider: (1) switching to a faster model for this step if quality allows, "
                    "(2) enabling streaming so the user sees output sooner, "
                    "(3) reducing prompt size to shorten generation time, "
                    "(4) caching the response if the input is deterministic."
                ),
                affected_span_ids=[span.span_id],
                evidence={
                    "span_duration_ms":   span.duration_ms,
                    "total_duration_ms":  signals.total_duration_ms,
                    "ratio":              round(ratio, 3),
                    "model":              span.model,
                },
            ))
        return insights
