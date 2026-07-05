from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# --- Tunable thresholds (see M3+ for per-workspace config) ---
_MIN_REPEATED_CALLS = 2  # need at least 2 calls with similar input to flag
_SIMILARITY_TOLERANCE = 0.05  # two calls are "same input" if within ±5% token count

# Minimum input tokens before caching is worthwhile, per provider.
# Sources: Anthropic docs (min 1024), OpenAI docs (min 1024 on GPT-4o+),
# Google Gemini docs (Flash: 1024, Pro: 4096).
_MIN_CACHE_TOKENS_DEFAULT = 1_024


@dataclass(frozen=True)
class _CacheConfig:
    min_tokens: int
    recommendation: str


def _provider_config(model: str) -> _CacheConfig:
    """Return caching threshold and recommendation for the given model in one lookup."""
    m = model.lower()
    if "claude" in m:
        return _CacheConfig(
            min_tokens=1_024,
            recommendation=(
                "Enable Anthropic prompt caching: add cache_control={'type': 'ephemeral'} "
                "to the system prompt and any large static blocks (documents, tool definitions). "
                "Cached prefixes must be ≥ 1024 tokens. Cache hits reduce latency by ~85% "
                "and cost 90% less than uncached input tokens."
            ),
        )
    if "gpt" in m or "o1" in m or "o3" in m:
        return _CacheConfig(
            min_tokens=1_024,
            recommendation=(
                "OpenAI prompt caching is automatic for prompts ≥ 1024 tokens on GPT-4o and "
                "later models — no API changes needed. Ensure your system prompt and static "
                "context appear at the start of every request so the cached prefix is reused. "
                "Cache hits are billed at 50% of the standard input token price."
            ),
        )
    if "gemini" in m:
        is_flash = "flash" in m
        min_tokens = 1_024 if is_flash else 4_096
        min_tok_str = "1,024" if is_flash else "4,096"
        return _CacheConfig(
            min_tokens=min_tokens,
            recommendation=(
                f"Use the Google Gemini Context Caching API to cache large static content "
                f"(system instructions, documents, tool definitions) before your request loop. "
                f"Minimum cacheable size for this model is {min_tok_str} tokens. "
                f"Cached tokens cost ~75% less than uncached input tokens (Gemini 2.5+)."
            ),
        )
    # Unknown provider — use conservative default
    return _CacheConfig(
        min_tokens=_MIN_CACHE_TOKENS_DEFAULT,
        recommendation=(
            "Check if your model provider supports prompt caching or KV-cache reuse for "
            "repeated large contexts. Move static content (system prompt, documents, tool "
            "definitions) to the beginning of your prompt so the provider can cache the prefix."
        ),
    )


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

    id = "context_cache_opportunity"
    name = "Context Cache Opportunity"
    severity = Severity.WARNING
    tier = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        # Collect LLM spans with input_tokens available
        llm_spans = [
            s
            for s in graph.nodes.values()
            if s.kind == SpanKind.LLM_CALL and s.input_tokens is not None
        ]
        if len(llm_spans) < _MIN_REPEATED_CALLS:
            return None

        # Group by model (None model is its own "unknown" group)
        by_model: dict[str, list[NormalizedSpan]] = defaultdict(list)
        for span in llm_spans:
            by_model[span.model or "unknown"].append(span)

        insights: list[Insight] = []

        for model, spans in by_model.items():
            if len(spans) < _MIN_REPEATED_CALLS:
                continue

            config = _provider_config(model)

            # Sort by input_tokens to make clustering O(n)
            spans.sort(key=lambda s: s.input_tokens or 0)

            # Sliding-window cluster: group spans whose input_tokens are within
            # ±5% of the cluster anchor (first span). The anchor is fixed for the
            # lifetime of the cluster, so drift is bounded: a cluster can span at
            # most 5% growth from the first call before a new cluster starts.
            clusters: list[list[NormalizedSpan]] = []
            current: list[NormalizedSpan] = [spans[0]]
            anchor_tokens: int = spans[0].input_tokens or 0

            for span in spans[1:]:
                if (span.input_tokens or 0) <= anchor_tokens * (1 + _SIMILARITY_TOLERANCE):
                    current.append(span)
                else:
                    if len(current) >= _MIN_REPEATED_CALLS:
                        clusters.append(current)
                    current = [span]
                    anchor_tokens = span.input_tokens or 0

            if len(current) >= _MIN_REPEATED_CALLS:
                clusters.append(current)

            for cluster in clusters:
                # Use median token count as representative — more accurate than
                # cluster[0] (minimum) which understates wasted tokens.
                representative_tokens = cluster[len(cluster) // 2].input_tokens or 0
                if representative_tokens < config.min_tokens:
                    continue

                call_count = len(cluster)
                wasted_tokens = representative_tokens * (call_count - 1)
                affected_ids = [s.span_id for s in cluster]

                insights.append(
                    Insight(
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
                        recommendation=config.recommendation,
                        affected_span_ids=affected_ids,
                        evidence={
                            "model": model,
                            "repeated_calls": call_count,
                            "input_tokens_per_call": representative_tokens,
                            "wasted_tokens": wasted_tokens,
                        },
                    )
                )

        return insights or None
