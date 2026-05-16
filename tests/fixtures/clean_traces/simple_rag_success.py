"""
Clean RAG pipeline: retrieval returns results, LLM follows, fast, no retries.
Grounded response — retrieval_without_grounding must not fire.
"""
from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from tests.fixtures.clean_traces._base import CleanTraceFixture

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, parent_id=None, offset_ms=0, duration_ms=200, **kwargs):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="clean-rag-1", parent_span_id=parent_id,
        name=span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws-test", **kwargs,
    )


FIXTURE = CleanTraceFixture(
    label="simple_rag_success",
    description=(
        "Standard RAG: retrieval returns 150 output tokens, LLM call follows. "
        "Single turn, no retries, latency balanced across spans."
    ),
    spans=[
        _span("root",      SpanKind.CHAIN,     offset_ms=0,   duration_ms=2000),
        _span("retrieve",  SpanKind.RETRIEVAL, parent_id="root", offset_ms=100, duration_ms=300,
              output_tokens=150),
        _span("llm_call",  SpanKind.LLM_CALL,  parent_id="root", offset_ms=500, duration_ms=700,
              input_tokens=400, output_tokens=200),
    ],
)
