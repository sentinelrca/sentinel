from __future__ import annotations

from collections import defaultdict

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# --- Tunable thresholds (see M3+ for per-workspace config) ---
_MIN_REPEATED_CALLS   = 2       # need at least 2 calls with similar input to flag
_SIMILARITY_TOLERANCE = 0.05    # two calls are "same input" if within ±5% token count

# Minimum input tokens before caching is worthwhile, per provider.
# Sources: Anthropic docs (min 1024), OpenAI docs (min 1024 on GPT-4o+),
# Google Gemini docs (Flash: 1024, Pro: 4096).
_MIN_CACHE_TOKENS_DEFAULT = 1_024


def _min_cache_tokens(model: str) -> int:
    m = model.lower()
    if "gemini" in m:
        return 1_024 if "flash" in m else 4_096  # pro models require 4096
    return _MIN_CACHE_TOKENS_DEFAULT  # Anthropic and OpenAI both require 1024


class ContextCacheOpportunityDetector(Detector):
    """
    Fires when multiple LLM calls within a trace send the same large context
    (system prompt, conversation history, retrieved documents) repeatedly to
    the same model — a clear prompt-caching opportunity.

    Detection signal: input_tokens is used as a proxy for prompt identity.
    Calls to the same model with input_tokens within ±5% of each other are
    treated as sending the same prefix. Actual content comparison is not
    performed since prompt content is not stored by default.

    Why token-count similarity works: within a single trace, identical
    input_tokens to the same model almost always means the same system
    prompt + context is being sent on every turn. Variance comes from
    growing conversation history, so we use ±5% tolerance to group calls
    from the same logical context window.

    All major providers support prompt caching:
      Anthropic  — cache_control on system/user blocks (min 1024 tokens)
      OpenAI     — automatic for prompts ≥ 1024 tokens on GPT-4o+
      Google     — explicit Context Caching API (Gemini 1.5+)
    """

    id       = "context_cache_opportunity"
    name     = "Context Cache Opportunity"
    severity = Severity.WARNING
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        # Collect LLM spans with input_tokens available
        llm_spans = [
            s for s in graph.nodes.values()
            if s.kind == SpanKind.LLM_CALL and s.input_tokens is not None
        ]
        if len(llm_spans) < _MIN_REPEATED_CALLS:
            return None

        # Group by model (unknown model is its own group)
        by_model: dict[str, list] = defaultdict(list)
        for span in llm_spans:
            by_model[span.model or "unknown"].append(span)

        insights: list[Insight] = []

        for model, spans in by_model.items():
            if len(spans) < _MIN_REPEATED_CALLS:
                continue

            # Sort by input_tokens to make clustering O(n)
            spans.sort(key=lambda s: s.input_tokens)

            # Sliding-window cluster: group spans whose input_tokens are
            # within ±5% of the group's anchor (first span in the cluster)
            clusters: list[list] = []
            current: list = [spans[0]]
            anchor_tokens: int = spans[0].input_tokens

            for span in spans[1:]:
                if span.input_tokens <= anchor_tokens * (1 + _SIMILARITY_TOLERANCE):
                    current.append(span)
                else:
                    if len(current) >= _MIN_REPEATED_CALLS:
                        clusters.append(current)
                    current = [span]
                    anchor_tokens = span.input_tokens

            if len(current) >= _MIN_REPEATED_CALLS:
                clusters.append(current)

            for cluster in clusters:
                representative_tokens = cluster[0].input_tokens
                if representative_tokens < _min_cache_tokens(model):
                    continue

                call_count    = len(cluster)
                # Tokens re-sent on every call after the first
                wasted_tokens = representative_tokens * (call_count - 1)
                affected_ids  = [s.span_id for s in cluster]

                insights.append(Insight(
                    workspace_id=graph.workspace_id,
                    trace_id=graph.trace_id,
                    detector_id=self.id,
                    severity=self.severity,
                    title=f"Repeated large context sent to {model} — cache it",
                    detail=(
                        f"{call_count} calls to {model} each sent ~{representative_tokens:,} "
                        f"input tokens. Sending the same large context on every call "
                        f"re-processes approximately {wasted_tokens:,} tokens that could "
                        f"be served from cache after the first call."
                    ),
                    recommendation=(
                        _cache_recommendation(model)
                    ),
                    affected_span_ids=affected_ids,
                    evidence={
                        "model":                model,
                        "repeated_calls":       call_count,
                        "input_tokens_per_call": representative_tokens,
                        "wasted_tokens":        wasted_tokens,
                    },
                ))

        return insights or None


def _cache_recommendation(model: str) -> str:
    m = model.lower()
    if "claude" in m:
        return (
            "Enable Anthropic prompt caching: add cache_control={'type': 'ephemeral'} "
            "to the system prompt and any large static blocks (documents, tool definitions). "
            "Cached prefixes must be ≥ 1024 tokens. Cache hits reduce latency by ~85% "
            "and cost 90% less than uncached input tokens."
        )
    if "gpt" in m or "o1" in m or "o3" in m:
        return (
            "OpenAI prompt caching is automatic for prompts ≥ 1024 tokens on GPT-4o and "
            "later models — no API changes needed. Ensure your system prompt and static "
            "context appear at the start of every request so the cached prefix is reused. "
            "Cache hits are billed at 50% of the standard input token price."
        )
    if "gemini" in m:
        min_tok = "1,024" if "flash" in m else "4,096"
        return (
            f"Use the Google Gemini Context Caching API to cache large static content "
            f"(system instructions, documents, tool definitions) before your request loop. "
            f"Minimum cacheable size for this model is {min_tok} tokens. "
            f"Cached tokens cost ~75% less than uncached input tokens (Gemini 2.5+)."
        )
    return (
        "Check if your model provider supports prompt caching or KV-cache reuse for "
        "repeated large contexts. Move static content (system prompt, documents, tool "
        "definitions) to the beginning of your prompt so the provider can cache the prefix."
    )
