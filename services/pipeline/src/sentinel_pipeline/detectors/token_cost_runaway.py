from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# Thresholds derived from observed p99 token usage across typical agentic workflows.
# Agents consume 5–30× more tokens than chatbots (LeanOps, 2026).
_MAX_INPUT_TOKENS = 50_000  # >50k input tokens in a single trace is anomalous
_MAX_OUTPUT_TOKENS = 10_000  # >10k output tokens suggests uncontrolled generation
_MAX_TOTAL_TOKENS = 100_000  # combined ceiling


class TokenCostRunawayDetector(Detector):
    """
    Fires when a single trace consumes anomalously high tokens, indicating
    runaway cost without budget controls.

    Literature basis: agentic models consume 5–30× more tokens than chatbots;
    self-built agents without prompt caching cost 5–10× more than instrumented
    versions. Teams with budget guardrails reduce costs 55–75% within 30 days
    (LeanOps research, 2026).
    """

    id = "token_cost_runaway"
    name = "Token Cost Runaway"
    severity = Severity.HIGH
    tier = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not graph.nodes:
            return None

        total_input = signals.total_input_tokens
        total_output = signals.total_output_tokens
        total = total_input + total_output

        breached_input = total_input > _MAX_INPUT_TOKENS
        breached_output = total_output > _MAX_OUTPUT_TOKENS
        breached_total = total > _MAX_TOTAL_TOKENS

        if not (breached_input or breached_output or breached_total):
            return None

        # Identify the top token-consuming LLM spans for evidence
        llm_spans = sorted(
            [s for s in graph.nodes.values() if s.kind == SpanKind.LLM_CALL and s.input_tokens],
            key=lambda s: (s.input_tokens or 0) + (s.output_tokens or 0),
            reverse=True,
        )
        top_consumers = [
            {
                "span_id": s.span_id,
                "name": s.name,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "model": s.model,
            }
            for s in llm_spans[:3]
        ]

        breaches = []
        if breached_input:
            breaches.append(f"input tokens ({total_input:,} > {_MAX_INPUT_TOKENS:,})")
        if breached_output:
            breaches.append(f"output tokens ({total_output:,} > {_MAX_OUTPUT_TOKENS:,})")
        if breached_total and not (breached_input and breached_output):
            breaches.append(f"total tokens ({total:,} > {_MAX_TOTAL_TOKENS:,})")

        return [
            Insight(
                workspace_id=graph.workspace_id,
                trace_id=graph.trace_id,
                detector_id=self.id,
                severity=self.severity,
                title="Token cost runaway detected",
                detail=(
                    f"This trace exceeded safe token thresholds: {'; '.join(breaches)}. "
                    f"At typical API pricing, this single trace costs $0.50–$5.00+. "
                    f"Agentic workflows without budget controls can burn through monthly "
                    f"budgets in hours."
                ),
                recommendation=(
                    "Add workflow-level token budget guards: "
                    "(1) Set a max_tokens budget per agent invocation. "
                    "(2) Enable prompt caching for repeated system prompts (saves 60–90% on input tokens). "
                    "(3) Use a smaller model for intermediate reasoning steps — reserve large models "
                    "for final synthesis. "
                    "(4) Add a kill-switch that terminates the workflow when cumulative tokens "
                    "exceed a per-trace budget."
                ),
                affected_span_ids=[str(s["span_id"]) for s in top_consumers],
                evidence={
                    "total_input_tokens": total_input,
                    "total_output_tokens": total_output,
                    "total_tokens": total,
                    "top_consumers": top_consumers,
                    "thresholds": {
                        "max_input_tokens": _MAX_INPUT_TOKENS,
                        "max_output_tokens": _MAX_OUTPUT_TOKENS,
                        "max_total_tokens": _MAX_TOTAL_TOKENS,
                    },
                },
            )
        ]
