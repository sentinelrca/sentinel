"""
Retrieval + LLM call run sequentially (retrieval feeds LLM) with balanced durations.
No single span exceeds 40% of total trace time — latency_spike must not fire.
Uses RETRIEVAL → LLM_CALL pattern (not sibling TOOL_INVOKEs) so sequential_tools
does not apply.
"""
from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from tests.fixtures.clean_traces._base import CleanTraceFixture

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, parent_id=None, offset_ms=0, duration_ms=300, **kwargs):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="clean-latency-1", parent_span_id=parent_id,
        name=span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws-test", **kwargs,
    )


FIXTURE = CleanTraceFixture(
    label="balanced_latency",
    description=(
        "Retrieval (900ms) → LLM call (1000ms) under a 3000ms root chain. "
        "Longest span is 33% of total — well under the 50% latency_spike threshold."
    ),
    spans=[
        _span("root",      SpanKind.CHAIN,     offset_ms=0,   duration_ms=3000),
        _span("retrieve",  SpanKind.RETRIEVAL,  parent_id="root", offset_ms=0,   duration_ms=900,
              output_tokens=150),
        _span("llm_call",  SpanKind.LLM_CALL,  parent_id="root", offset_ms=950,  duration_ms=1000,
              input_tokens=400, output_tokens=200),
    ],
)
