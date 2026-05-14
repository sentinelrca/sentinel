from __future__ import annotations

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Rule


class RetrievalWithoutGroundingRule(Rule):
    id       = "retrieval_without_grounding"
    name     = "Retrieval Without Grounding"
    severity = Severity.HIGH
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not graph.nodes:
            return None

        dg = graph.digraph
        insights: list[Insight] = []

        for span in graph.nodes.values():
            if span.kind != SpanKind.RETRIEVAL:
                continue

            # A retrieval span with zero output tokens returned nothing
            returned_nothing = (
                span.output_tokens is not None and span.output_tokens == 0
            ) or span.attributes.get("retrieval.result_count", -1) == 0

            if not returned_nothing:
                continue

            # Check if an LLM call follows (sibling or descendant of same parent)
            parent_id = span.parent_span_id
            siblings = (
                [
                    graph.nodes[nid]
                    for nid in dg.successors(parent_id)
                    if nid in graph.nodes
                ]
                if parent_id and parent_id in graph.nodes
                else [s for s in graph.nodes.values() if s.parent_span_id is None]
            )

            following_llm_calls = [
                s for s in siblings
                if s.kind == SpanKind.LLM_CALL
                and s.start_time >= span.start_time
                and s.span_id != span.span_id
            ]

            if not following_llm_calls:
                continue

            llm_ids = [s.span_id for s in following_llm_calls]
            insights.append(Insight(
                workspace_id=graph.workspace_id,
                trace_id=graph.trace_id,
                rule_id=self.id,
                severity=self.severity,
                title=f"LLM called after empty retrieval in '{span.name}'",
                detail=(
                    f"Retrieval span '{span.name}' returned no results "
                    f"(output_tokens=0), but {len(following_llm_calls)} LLM call(s) "
                    "were made afterwards. The model will hallucinate — it has no "
                    "grounding documents to cite or constrain its answer."
                ),
                recommendation=(
                    "Check retrieval results before calling the LLM. "
                    "If retrieval is empty, surface 'Insufficient context' to the user "
                    "instead of forwarding to the model. "
                    "Never let a model answer questions it has no evidence for."
                ),
                affected_span_ids=[span.span_id] + llm_ids,
                evidence={
                    "retrieval_span_id": span.span_id,
                    "retrieval_name":    span.name,
                    "llm_span_ids":      llm_ids,
                },
            ))

        return insights or None
