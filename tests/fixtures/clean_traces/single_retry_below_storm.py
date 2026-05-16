"""
Tool retried once (retry_count=2), which is below the retry_storm threshold of 3.
Verifies the rule boundary: 2 retries is acceptable, 3+ is a storm.
"""
from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from tests.fixtures.clean_traces._base import CleanTraceFixture

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, parent_id=None, offset_ms=0, duration_ms=300, **kwargs):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="clean-retry-1", parent_span_id=parent_id,
        name=span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws-test", **kwargs,
    )


FIXTURE = CleanTraceFixture(
    label="single_retry_below_storm",
    description=(
        "fetch_api retried twice (retry_count=2). "
        "Threshold for retry_storm is 3 — this must not fire."
    ),
    spans=[
        _span("root",       SpanKind.CHAIN,       offset_ms=0,    duration_ms=2000),
        _span("fetch_api",  SpanKind.TOOL_INVOKE,  parent_id="root", offset_ms=100,
              duration_ms=600, retry_count=2),
        _span("llm_call",   SpanKind.LLM_CALL,    parent_id="root", offset_ms=800,
              duration_ms=500, input_tokens=300, output_tokens=150),
    ],
)
