from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Detector

# --- Tunable thresholds (see M3+ for per-workspace config) ---
_MIN_TOKEN_GROWTH_RATIO    = 0.10   # expect ≥10% input token growth after retrieval
_MIN_OVERLAP_RATIO         = 0.05   # Jaccard threshold for content-based grounding check
_MIN_INPUT_TOKENS_TO_CHECK = 500    # skip token growth check for very small prompts

# Tool invoke names that indicate retrieval when SpanKind.RETRIEVAL is absent.
# Covers OTel-based frameworks (Google ADK, AutoGen) that emit retrieval as tool calls.
_RETRIEVAL_NAME_PATTERNS = frozenset({
    "retrieve", "search", "similarity_search", "vector_search",
    "query", "lookup", "retriever",
})


def _get_retrieval_spans(graph: FlowGraph) -> list[NormalizedSpan]:
    """Return retrieval spans. Prefer explicit SpanKind; fall back to tool name patterns."""
    explicit = [s for s in graph.nodes.values() if s.kind == SpanKind.RETRIEVAL]
    if explicit:
        return explicit
    return [
        s for s in graph.nodes.values()
        if s.kind == SpanKind.TOOL_INVOKE
        and any(kw in s.name.lower() for kw in _RETRIEVAL_NAME_PATTERNS)
    ]


def _token_overlap(a: str, b: str) -> float:
    """Jaccard similarity on whitespace-tokenised words."""
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def _content_str(value: object) -> str:
    """Flatten gen_ai.input / gen_ai.output to a plain string for overlap comparison."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value) if value else ""


class RetrievalWithoutGroundingDetector(Detector):
    """
    Fires when a trace performs retrieval (RAG) but the retrieved content
    does not appear to be used in the subsequent LLM response.

    Two detection modes, selected automatically:

    Content mode (store_content=True):
      Compares the retrieved content (gen_ai.input on the retrieval span)
      against the LLM response (gen_ai.output on the following LLM span)
      using Jaccard token overlap. Overlap < 5% → grounding failure.
      Fires HIGH — definitive evidence.

    Structural mode (store_content=False):
      Signal 1 — no LLM call after retrieval: definitive miss.
      Signal 2 — input tokens don't grow after retrieval: retrieved content
        likely not injected into the prompt (heuristic, low-confidence).
      Fires WARNING.

    Retrieval span resolution:
      1. SpanKind.RETRIEVAL (LangChain-based stacks — precise)
      2. TOOL_INVOKE whose name matches retrieval-like patterns
         (OTel-based stacks: Google ADK, AutoGen, etc. — best effort)
    """

    id       = "retrieval_without_grounding"
    name     = "Retrieval Without Grounding"
    severity = Severity.WARNING
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        retrieval_spans = _get_retrieval_spans(graph)
        if not retrieval_spans:
            return None

        llm_spans = [s for s in graph.nodes.values() if s.kind == SpanKind.LLM_CALL]

        # Try content-based check first
        insight = self._check_with_content(graph, retrieval_spans, llm_spans)
        if insight is not None:
            return [insight]

        # Fall back to structural check
        insight = self._check_structural(graph, retrieval_spans, llm_spans)
        if insight is not None:
            return [insight]

        return None

    # ------------------------------------------------------------------

    def _check_with_content(
        self,
        graph: FlowGraph,
        retrieval_spans: list[NormalizedSpan],
        llm_spans: list[NormalizedSpan],
    ) -> Insight | None:
        for ret_span in sorted(retrieval_spans, key=lambda s: s.start_time):
            retrieved_raw = ret_span.attributes.get("gen_ai.input")
            if not retrieved_raw:
                continue
            retrieved_text = _content_str(retrieved_raw)
            if not retrieved_text.strip():
                continue

            # Find the first LLM call after this retrieval span
            subsequent = sorted(
                [s for s in llm_spans if s.start_time > ret_span.end_time],
                key=lambda s: s.start_time,
            )
            for llm_span in subsequent:
                response_raw = llm_span.attributes.get("gen_ai.output")
                if not response_raw:
                    continue
                response_text = _content_str(response_raw)
                if not response_text.strip():
                    continue

                overlap = _token_overlap(retrieved_text, response_text)
                if overlap < _MIN_OVERLAP_RATIO:
                    return Insight(
                        workspace_id=graph.workspace_id,
                        trace_id=graph.trace_id,
                        detector_id=self.id,
                        severity=Severity.HIGH,
                        title="LLM response not grounded in retrieved content",
                        detail=(
                            f"Retrieval span '{ret_span.name}' fetched content, but the "
                            f"subsequent LLM response has only {overlap:.1%} token overlap "
                            f"with the retrieved text. A well-grounded RAG response typically "
                            f"shares key terms, entities, and phrases with its source documents."
                        ),
                        recommendation=(
                            "Check that retrieved documents are correctly injected into the "
                            "LLM prompt. Common causes: retrieved chunks appended after the "
                            "user message instead of in a system/context block; empty retrieval "
                            "results not handled before calling the LLM; prompt template not "
                            "referencing the {context} variable. Enable verbose logging on your "
                            "retriever to inspect what is returned and passed downstream."
                        ),
                        affected_span_ids=[ret_span.span_id, llm_span.span_id],
                        evidence={
                            "retrieval_span":  ret_span.span_id,
                            "llm_span":        llm_span.span_id,
                            "overlap_ratio":   round(overlap, 4),
                            "detection_mode":  "content",
                        },
                    )
        return None

    def _check_structural(
        self,
        graph: FlowGraph,
        retrieval_spans: list[NormalizedSpan],
        llm_spans: list[NormalizedSpan],
    ) -> Insight | None:
        # Signal 1: no LLM call after any retrieval span
        for ret_span in retrieval_spans:
            subsequent = [s for s in llm_spans if s.start_time > ret_span.end_time]
            if not subsequent:
                return Insight(
                    workspace_id=graph.workspace_id,
                    trace_id=graph.trace_id,
                    detector_id=self.id,
                    severity=self.severity,
                    title="Retrieval result never consumed by an LLM call",
                    detail=(
                        f"Retrieval span '{ret_span.name}' completed but no LLM call "
                        f"follows it in the trace. The retrieved content was never passed "
                        f"to a language model — the retrieval cost (latency + vector DB "
                        f"query) was wasted and any LLM response in this trace is "
                        f"ungrounded."
                    ),
                    recommendation=(
                        "Ensure your retrieval step is called before the LLM call and that "
                        "the retrieved documents are injected into the prompt. Check for "
                        "async/await issues or early-return paths that skip the LLM call "
                        "after retrieval."
                    ),
                    affected_span_ids=[ret_span.span_id],
                    evidence={
                        "retrieval_span": ret_span.span_id,
                        "detection_mode": "structural_no_llm_after_retrieval",
                    },
                )

        # Signal 2: LLM input tokens don't grow after retrieval
        first_ret_time = min(s.start_time for s in retrieval_spans)
        llm_before = [
            s for s in llm_spans
            if s.start_time < first_ret_time and s.input_tokens
            and s.input_tokens >= _MIN_INPUT_TOKENS_TO_CHECK
        ]
        llm_after = [
            s for s in llm_spans
            if s.start_time > first_ret_time and s.input_tokens
            and s.input_tokens >= _MIN_INPUT_TOKENS_TO_CHECK
        ]

        if not llm_before or not llm_after:
            return None  # can't establish a baseline

        avg_before = sum(s.input_tokens for s in llm_before) / len(llm_before)
        avg_after  = sum(s.input_tokens for s in llm_after)  / len(llm_after)
        growth     = (avg_after - avg_before) / avg_before if avg_before > 0 else 0.0

        if growth < _MIN_TOKEN_GROWTH_RATIO:
            return Insight(
                workspace_id=graph.workspace_id,
                trace_id=graph.trace_id,
                detector_id=self.id,
                severity=self.severity,
                title="LLM prompt shows no growth after retrieval — content may not be injected",
                detail=(
                    f"LLM calls before retrieval averaged {avg_before:,.0f} input tokens; "
                    f"calls after retrieval averaged {avg_after:,.0f} tokens "
                    f"({growth:+.1%} change). Injecting retrieved chunks into the prompt "
                    f"should increase input tokens noticeably. The lack of growth suggests "
                    f"retrieved content may not be reaching the LLM."
                ),
                recommendation=(
                    "Verify your prompt construction: the retrieved documents should be "
                    "appended to the prompt before the LLM call. Enable content storage "
                    "(store_content=True) to get a definitive grounding analysis with "
                    "token overlap measurement."
                ),
                affected_span_ids=[s.span_id for s in retrieval_spans],
                evidence={
                    "avg_tokens_before_retrieval": round(avg_before),
                    "avg_tokens_after_retrieval":  round(avg_after),
                    "growth_ratio":                round(growth, 4),
                    "detection_mode":              "structural_no_token_growth",
                },
            )

        return None
