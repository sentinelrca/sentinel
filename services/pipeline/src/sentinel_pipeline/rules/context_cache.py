from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Rule

_TOKEN_GROWTH_THRESHOLD = 300  # input tokens growing by this much per successive LLM call


class ContextCacheOpportunityRule(Rule):
    id       = "context_cache_opportunity"
    name     = "Context Cache Opportunity"
    severity = Severity.WARNING
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not graph.nodes:
            return None

        llm_calls = sorted(
            [s for s in graph.nodes.values() if s.kind == SpanKind.LLM_CALL and s.input_tokens],
            key=lambda s: s.start_time,
        )

        if len(llm_calls) < 2:
            return None

        # Check if input tokens are consistently growing across consecutive LLM calls
        growing_pairs: list[tuple] = []
        for i in range(1, len(llm_calls)):
            prev = llm_calls[i - 1]
            curr = llm_calls[i]
            delta = (curr.input_tokens or 0) - (prev.input_tokens or 0)
            if delta >= _TOKEN_GROWTH_THRESHOLD:
                growing_pairs.append((prev, curr, delta))

        if not growing_pairs:
            return None

        first_tokens  = llm_calls[0].input_tokens or 0
        last_tokens   = llm_calls[-1].input_tokens or 0
        total_growth  = last_tokens - first_tokens
        affected_ids  = list(dict.fromkeys(
            sid for p in growing_pairs for sid in (p[0].span_id, p[1].span_id)
        ))

        return [Insight(
            workspace_id=graph.workspace_id,
            trace_id=graph.trace_id,
            rule_id=self.id,
            severity=self.severity,
            title="Input tokens growing across LLM calls — cache opportunity",
            detail=(
                f"Input tokens grew from {first_tokens} to {last_tokens} "
                f"(+{total_growth} tokens) across {len(llm_calls)} LLM calls. "
                f"{len(growing_pairs)} consecutive pair(s) grew by ≥{_TOKEN_GROWTH_THRESHOLD} tokens. "
                "A static system prompt or document context is likely being resent in full each call."
            ),
            recommendation=(
                "Use prompt caching (Anthropic prompt cache, OpenAI cached inputs) for the "
                "static prefix of your system prompt. For growing conversation history, "
                "summarise earlier turns rather than appending the full transcript."
            ),
            affected_span_ids=affected_ids,
            evidence={
                "first_input_tokens": first_tokens,
                "last_input_tokens":  last_tokens,
                "total_growth":       total_growth,
                "llm_call_count":     len(llm_calls),
                "growing_pairs":      len(growing_pairs),
            },
        )]
