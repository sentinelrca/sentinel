"""Unit tests for the redesigned analyze_project task (uses project_spans snapshot)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus


# ---------------------------------------------------------------------------
# Helpers (shared with test_import_project_traces pattern)
# ---------------------------------------------------------------------------

def _make_span(span_id: str = "s-1", trace_id: str = "t-1") -> NormalizedSpan:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return NormalizedSpan(
        span_id=span_id,
        trace_id=trace_id,
        name="test",
        kind=SpanKind.LLM_CALL,
        status=SpanStatus.OK,
        start_time=now,
        end_time=now,
        workspace_id="ws-1",
    )


def _span_row(span: NormalizedSpan) -> dict:
    """Simulate the dict shape returned by fetch_project_spans."""
    return {
        "project_id":    "proj-1",
        "trace_id":      span.trace_id,
        "span_id":       span.span_id,
        "parent_span_id": "",
        "workspace_id":  span.workspace_id,
        "name":          span.name,
        "kind":          span.kind.value,
        "status":        span.status.value,
        "start_time":    span.start_time,
        "end_time":      span.end_time,
        "model":         "",
        "agent_name":    "",
        "input_tokens":  0,
        "output_tokens": 0,
        "retry_count":   0,
        "error_message": "",
        "attributes_json": "{}",
    }


def _make_project(status: str = "ready") -> MagicMock:
    p = MagicMock()
    p.id = "proj-1"
    p.workspace_id = "ws-1"
    p.status = status
    p.last_analyzed_at = None
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_uses_project_spans_not_live_spans():
    """fetch_project_spans is called; fetch_spans_by_filter must NOT be called."""
    span = _make_span()
    project = _make_project(status="ready")
    row = _span_row(span)

    with (
        patch("sentinel_worker.tasks.analyze_project.fetch_project_spans",
              return_value=[row]) as mock_fetch,
        patch("sentinel_worker.tasks.analyze_project.build_graph") as mock_graph,
        patch("sentinel_worker.tasks.analyze_project.run_detectors", return_value=[]),
        patch("sentinel_worker.tasks.analyze_project.get_session") as mock_session_cm,
    ):
        mock_graph.return_value = MagicMock()
        _setup_session_sequence(mock_session_cm, [
            (project,),        # load project
            (project,),        # set status=analyzing
            (),                # load rule configs (empty)
            (None, project),   # delete insights (unused) + select project for timestamp
        ])

        from sentinel_worker.tasks.analyze_project import _analyze_project
        result = await _analyze_project("proj-1", "ws-1", tier=_tier(0))

    mock_fetch.assert_called_once_with("proj-1", "ws-1")
    assert result["insights"] == 0


@pytest.mark.asyncio
async def test_analyze_skips_when_status_not_ready():
    """When project.status != 'ready', task returns early with skipped=True."""
    for bad_status in ("pending", "importing", "error"):
        project = _make_project(status=bad_status)

        with (
            patch("sentinel_worker.tasks.analyze_project.fetch_project_spans") as mock_fetch,
            patch("sentinel_worker.tasks.analyze_project.get_session") as mock_session_cm,
        ):
            _setup_session_sequence(mock_session_cm, [(project,)])

            from sentinel_worker.tasks.analyze_project import _analyze_project
            result = await _analyze_project("proj-1", "ws-1", tier=_tier(0))

        assert result.get("skipped") is True, f"Expected skipped=True for status={bad_status}"
        mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_returns_early_when_project_not_found():
    """Missing project returns zeros without raising."""
    with (
        patch("sentinel_worker.tasks.analyze_project.fetch_project_spans") as mock_fetch,
        patch("sentinel_worker.tasks.analyze_project.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [(None,)])

        from sentinel_worker.tasks.analyze_project import _analyze_project
        result = await _analyze_project("proj-missing", "ws-1", tier=_tier(0))

    assert result["insights"] == 0
    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_returns_early_when_no_spans():
    """Empty project_spans returns zero insights without running rules."""
    project = _make_project(status="ready")

    with (
        patch("sentinel_worker.tasks.analyze_project.fetch_project_spans", return_value=[]),
        patch("sentinel_worker.tasks.analyze_project.run_detectors") as mock_rules,
        patch("sentinel_worker.tasks.analyze_project.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [
            (project,),  # load project
            (project,),  # set status=analyzing
            (project,),  # reset status=ready (no spans path)
        ])

        from sentinel_worker.tasks.analyze_project import _analyze_project
        result = await _analyze_project("proj-1", "ws-1", tier=_tier(0))

    assert result["insights"] == 0
    mock_rules.assert_not_called()


@pytest.mark.asyncio
async def test_analyze_persists_insights_with_project_id():
    """Insights written to DB must have project_id set (not None)."""
    span = _make_span()
    project = _make_project(status="ready")
    row = _span_row(span)

    mock_insight = MagicMock()
    mock_insight.id = "ins-1"
    mock_insight.workspace_id = "ws-1"
    mock_insight.trace_id = "t-1"
    mock_insight.detector_id = "agent_loop"
    mock_insight.severity = MagicMock(value="high")
    mock_insight.title = "Loop detected"
    mock_insight.detail = "..."
    mock_insight.recommendation = "fix it"
    mock_insight.affected_span_ids = ["s-1"]
    mock_insight.evidence = {}

    added_rows: list = []

    with (
        patch("sentinel_worker.tasks.analyze_project.fetch_project_spans", return_value=[row]),
        patch("sentinel_worker.tasks.analyze_project.build_graph", return_value=MagicMock()),
        patch("sentinel_worker.tasks.analyze_project.run_detectors", return_value=[mock_insight]),
        patch("sentinel_worker.tasks.analyze_project.get_session") as mock_session_cm,
    ):
        def _capture_add(session):
            def _add(obj):
                added_rows.append(obj)
            session.add = _add

        sessions = [
            _make_mock_session((project,), on_create=_capture_add),       # load project
            _make_mock_session((project,), on_create=_capture_add),       # set status=analyzing
            _make_mock_session((), on_create=_capture_add),                # rule configs (empty)
            _make_mock_session((None, project), on_create=_capture_add),   # delete (unused) + select for timestamp
        ]
        mock_session_cm.side_effect = _build_async_cm_side_effect(sessions)

        from sentinel_worker.tasks.analyze_project import _analyze_project
        result = await _analyze_project("proj-1", "ws-1", tier=_tier(0))

    assert result["insights"] == 1
    insight_rows = [r for r in added_rows if hasattr(r, "project_id")]
    assert len(insight_rows) == 1
    assert insight_rows[0].project_id == "proj-1"


@pytest.mark.asyncio
async def test_analyze_updates_last_analyzed_at():
    """last_analyzed_at is updated on the project row after a successful run."""
    span = _make_span()
    project = _make_project(status="ready")
    row = _span_row(span)

    with (
        patch("sentinel_worker.tasks.analyze_project.fetch_project_spans", return_value=[row]),
        patch("sentinel_worker.tasks.analyze_project.build_graph", return_value=MagicMock()),
        patch("sentinel_worker.tasks.analyze_project.run_detectors", return_value=[]),
        patch("sentinel_worker.tasks.analyze_project.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [
            (project,),         # load project
            (project,),         # set status=analyzing
            (),                 # rule configs
            (None, project),    # delete insights (unused result) + select project for timestamp
        ])

        from sentinel_worker.tasks.analyze_project import _analyze_project
        await _analyze_project("proj-1", "ws-1", tier=_tier(0))

    assert project.last_analyzed_at is not None


@pytest.mark.asyncio
async def test_analyze_groups_spans_by_trace_and_runs_rules_per_trace():
    """Spans from two different traces → run_detectors called twice."""
    spans = [_make_span(f"s-{i}", f"t-{i}") for i in range(2)]
    rows = [_span_row(s) for s in spans]
    project = _make_project(status="ready")

    with (
        patch("sentinel_worker.tasks.analyze_project.fetch_project_spans", return_value=rows),
        patch("sentinel_worker.tasks.analyze_project.build_graph", return_value=MagicMock()),
        patch("sentinel_worker.tasks.analyze_project.run_detectors", return_value=[]) as mock_rules,
        patch("sentinel_worker.tasks.analyze_project.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [(project,), (project,), (), (None, project)])

        from sentinel_worker.tasks.analyze_project import _analyze_project
        await _analyze_project("proj-1", "ws-1", tier=_tier(0))

    assert mock_rules.call_count == 2


# ---------------------------------------------------------------------------
# Session mock helpers (mirrors test_import_project_traces)
# ---------------------------------------------------------------------------

def _tier(value: int):
    from sentinel_pipeline.models.insight import Tier
    return Tier(value)


def _setup_session_sequence(mock_session_cm, call_data: list):
    sessions = [_make_mock_session(items) for items in call_data]
    mock_session_cm.side_effect = _build_async_cm_side_effect(sessions)


def _make_mock_session(items: tuple, on_create=None) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.add = MagicMock()

    if on_create:
        on_create(session)

    results = list(items)
    result_iter = iter(results)

    def _execute_side_effect(*args, **kwargs):
        try:
            value = next(result_iter)
        except StopIteration:
            value = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = value
        mock_result.scalar_one.return_value = value
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = value
        scalars_mock.all.return_value = [] if value is None else (
            list(value) if hasattr(value, "__iter__") and not isinstance(value, MagicMock)
            else [value]
        )
        mock_result.scalars.return_value = scalars_mock
        return mock_result

    session.execute = AsyncMock(side_effect=_execute_side_effect)
    return session


def _build_async_cm_side_effect(sessions: list):
    session_iter = iter(sessions)

    class _ACM:
        def __init__(self):
            try:
                self._session = next(session_iter)
            except StopIteration:
                self._session = _make_mock_session(())

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, *args):
            return False

    def _side_effect():
        return _ACM()

    return _side_effect


# ---------------------------------------------------------------------------
# _dedupe_insights — collapse multiple insights per (trace, detector)
# ---------------------------------------------------------------------------

def _make_insight(trace_id, detector_id, severity, span_ids):
    from sentinel_pipeline.models.insight import Insight, Severity
    return Insight(
        workspace_id="ws-1",
        trace_id=trace_id,
        detector_id=detector_id,
        severity=Severity(severity),
        title="t",
        detail="d",
        recommendation="r",
        affected_span_ids=list(span_ids),
    )


def test_dedupe_keeps_one_per_trace_detector_highest_severity():
    from sentinel_worker.tasks.analyze_project import _dedupe_insights
    ins = [
        _make_insight("t-1", "agent_loop", "warning", ["a", "b"]),
        _make_insight("t-1", "agent_loop", "high", ["b", "c"]),  # higher severity wins
    ]
    out = _dedupe_insights(ins)
    assert len(out) == 1
    assert out[0].severity.value == "high"
    # affected spans merged + de-duplicated, first-appearance order preserved
    assert out[0].affected_span_ids == ["a", "b", "c"]


def test_dedupe_preserves_distinct_keys():
    from sentinel_worker.tasks.analyze_project import _dedupe_insights
    ins = [
        _make_insight("t-1", "agent_loop", "high", ["a"]),
        _make_insight("t-1", "latency_spike", "high", ["b"]),   # different detector
        _make_insight("t-2", "agent_loop", "high", ["c"]),      # different trace
    ]
    out = _dedupe_insights(ins)
    assert len(out) == 3


def test_dedupe_empty_list():
    from sentinel_worker.tasks.analyze_project import _dedupe_insights
    assert _dedupe_insights([]) == []
