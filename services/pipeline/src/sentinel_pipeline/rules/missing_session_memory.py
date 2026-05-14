from __future__ import annotations

import re

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.models.span import SpanKind
from sentinel_pipeline.signals.extractor import Signals
from .base import Rule

_MIN_LLM_TURNS        = 3
_TOKEN_GROWTH_RATIO   = 1.50   # input tokens must grow ≥ 50% from turn 1 to turn N
_MEMORY_TOOL_PATTERN  = re.compile(
    r"mem|store|retrieve|recall|zep|remember|history|summary", re.IGNORECASE
)


class MissingSessionMemoryRule(Rule):
    id       = "missing_session_memory"
    name     = "Missing Session Memory"
    severity = Severity.WARNING
    tier     = Tier.FREE

    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        if not graph.nodes:
            return None

        llm_calls = sorted(
            [s for s in graph.nodes.values() if s.kind == SpanKind.LLM_CALL and s.input_tokens],
            key=lambda s: s.start_time,
        )

        if len(llm_calls) < _MIN_LLM_TURNS:
            return None

        first_tokens = llm_calls[0].input_tokens or 0
        last_tokens  = llm_calls[-1].input_tokens or 0

        if first_tokens == 0:
            return None

        growth_ratio = last_tokens / first_tokens
        if growth_ratio < _TOKEN_GROWTH_RATIO:
            return None

        # Check if any TOOL_INVOKE spans look like memory operations
        tool_names = [
            s.name for s in graph.nodes.values()
            if s.kind == SpanKind.TOOL_INVOKE and s.name
        ]
        has_memory_tool = any(_MEMORY_TOOL_PATTERN.search(name) for name in tool_names)

        if has_memory_tool:
            return None

        affected_ids = [s.span_id for s in llm_calls]

        return [Insight(
            workspace_id=graph.workspace_id,
            trace_id=graph.trace_id,
            rule_id=self.id,
            severity=self.severity,
            title="Input tokens growing — no session memory tool detected",
            detail=(
                f"Input tokens grew {growth_ratio:.1f}× across {len(llm_calls)} LLM calls "
                f"({first_tokens} → {last_tokens} tokens). "
                "No memory tool (store/retrieve/recall/Zep) was detected in the trace. "
                "The agent is likely re-sending the full conversation history on every turn, "
                "which wastes tokens and breaks at context window limits."
            ),
            recommendation=(
                "Add a session memory layer: store a summary of prior turns instead of "
                "the full transcript. Options: LangChain ConversationSummaryMemory, "
                "Zep, MemGPT, or a custom summarisation step before each LLM call. "
                "Memory tools reduce input tokens and let the agent scale across long sessions."
            ),
            affected_span_ids=affected_ids,
            evidence={
                "llm_call_count":     len(llm_calls),
                "first_input_tokens": first_tokens,
                "last_input_tokens":  last_tokens,
                "growth_ratio":       round(growth_ratio, 2),
                "memory_tools_found": False,
            },
        )]
