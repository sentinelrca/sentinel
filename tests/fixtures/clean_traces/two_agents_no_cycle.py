"""
Two agents hand off once — A invokes B, B completes. No back-edge, no repetition.
agent_loop fires on 3+ invocations of the same agent; this must not fire.
"""
from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from tests.fixtures.clean_traces._base import CleanTraceFixture

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, agent_name=None, parent_id=None, offset_ms=0, duration_ms=300):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="clean-agents-1", parent_span_id=parent_id,
        name=span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws-test", agent_name=agent_name,
    )


FIXTURE = CleanTraceFixture(
    label="two_agents_no_cycle",
    description=(
        "AgentA invokes AgentB exactly once. "
        "Each agent appears once — well below the loop threshold."
    ),
    spans=[
        _span("root",    SpanKind.CHAIN,        offset_ms=0,   duration_ms=2000),
        _span("agent_a", SpanKind.AGENT_INVOKE,  parent_id="root",    offset_ms=0,
              duration_ms=800, agent_name="AgentA"),
        _span("agent_b", SpanKind.AGENT_INVOKE,  parent_id="agent_a", offset_ms=100,
              duration_ms=600, agent_name="AgentB"),
    ],
)
