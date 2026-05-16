"""
Two tools run sequentially because B consumes A's output — correctly sequential.

Known limitation: sequential_tools currently cannot distinguish data-dependent
sequencing from accidentally-serial independent tools.  The rule fires on sibling
tool spans regardless of dependency.  This fixture documents that limitation and
should be updated (known_false_positives cleared) once the rule is improved.
"""
from datetime import datetime, timedelta, timezone

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from tests.fixtures.clean_traces._base import CleanTraceFixture

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _span(span_id, kind, parent_id=None, offset_ms=0, duration_ms=500):
    t0 = _T0 + timedelta(milliseconds=offset_ms)
    return NormalizedSpan(
        span_id=span_id, trace_id="clean-seq-dep-1", parent_span_id=parent_id,
        name=span_id, kind=kind, status=SpanStatus.OK,
        start_time=t0, end_time=t0 + timedelta(milliseconds=duration_ms),
        workspace_id="ws-test",
    )


FIXTURE = CleanTraceFixture(
    label="sequential_tools_data_dependency",
    description=(
        "search_docs runs first; summarize_results depends on its output and runs after. "
        "Sequencing is intentional — parallelising these would be incorrect."
    ),
    # sequential_tools fires because it sees sibling TOOL_INVOKE spans with no overlap.
    # This is a false positive: the dependency makes sequential ordering correct here.
    known_false_positives=["sequential_tools"],
    spans=[
        _span("root",             SpanKind.CHAIN,       offset_ms=0,    duration_ms=1500),
        _span("search_docs",      SpanKind.TOOL_INVOKE,  parent_id="root", offset_ms=0,    duration_ms=600),
        _span("summarize_results", SpanKind.TOOL_INVOKE, parent_id="root", offset_ms=650,   duration_ms=600),
    ],
)
