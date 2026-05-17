"""Unit tests for import_project_traces task."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus


# ---------------------------------------------------------------------------
# Helpers
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


def _make_project(
    status: str = "pending",
    import_count: int = 0,
    last_imported_at: datetime | None = None,
    filters: dict | None = None,
):
    p = MagicMock()
    p.id = "proj-1"
    p.workspace_id = "ws-1"
    p.status = status
    p.import_count = import_count
    p.last_imported_at = last_imported_at
    p.trace_count = 0
    p.filters = filters or {"date_from": "2026-01-01T00:00:00+00:00", "date_to": "2026-01-02T00:00:00+00:00"}
    return p


def _make_source(kind: str = "langfuse") -> MagicMock:
    s = MagicMock()
    s.kind = kind
    s.workspace_id = "ws-1"
    s.config_json = {"public_key": "pk", "secret_key": "sk", "base_url": "https://cloud.langfuse.com"}
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_calls_pull_by_window_and_inserts():
    """Happy path: pull_by_window called, spans inserted, status → ready."""
    span = _make_span()
    project = _make_project()
    source = _make_source()

    mock_connector = MagicMock()
    mock_connector.pull_by_window.return_value = iter([[span]])

    with (
        patch("sentinel_worker.tasks.import_project_traces.get_import_limits",
              return_value={"imports_per_week": None, "traces_per_import": None}),
        patch("sentinel_worker.tasks.import_project_traces._get_connector",
              return_value=mock_connector),
        patch("sentinel_worker.tasks.import_project_traces.insert_project_spans") as mock_insert,
        patch("sentinel_worker.tasks.import_project_traces.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [
            # quota unlimited → no count query; execute calls: project, source
            (project, source),
            # call 2: update status on success
            (project,),
        ])

        from sentinel_worker.tasks.import_project_traces import _import_project_traces
        result = await _import_project_traces("proj-1", "ws-1", workspace_tier=1)

    assert result["spans"] == 1
    assert result["traces"] == 1
    mock_insert.assert_called_once()
    assert project.status == "ready"
    assert project.import_count == 1
    assert project.last_imported_at is not None


@pytest.mark.asyncio
async def test_import_calls_pull_by_ids_when_trace_ids_in_filters():
    """When filters.trace_ids is set, pull_by_ids is used instead of pull_by_window."""
    span = _make_span()
    project = _make_project(filters={"trace_ids": ["t-abc", "t-def"]})
    source = _make_source()

    mock_connector = MagicMock()
    mock_connector.pull_by_ids.return_value = iter([[span]])

    with (
        patch("sentinel_worker.tasks.import_project_traces.get_import_limits",
              return_value={"imports_per_week": None, "traces_per_import": None}),
        patch("sentinel_worker.tasks.import_project_traces._get_connector",
              return_value=mock_connector),
        patch("sentinel_worker.tasks.import_project_traces.insert_project_spans"),
        patch("sentinel_worker.tasks.import_project_traces.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [(project, source), (project,)])

        from sentinel_worker.tasks.import_project_traces import _import_project_traces
        await _import_project_traces("proj-1", "ws-1", workspace_tier=1)

    mock_connector.pull_by_ids.assert_called_once_with(
        source.config_json, ["t-abc", "t-def"], "ws-1"
    )
    mock_connector.pull_by_window.assert_not_called()


@pytest.mark.asyncio
async def test_quota_exceeded_sets_error_status():
    """When imports_this_week >= limit, status → error and error key returned."""
    # Project has been imported 3 times in the last 7 days
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    existing_projects = [_make_project(last_imported_at=recent) for _ in range(3)]
    project = _make_project()

    with (
        patch("sentinel_worker.tasks.import_project_traces.get_import_limits",
              return_value={"imports_per_week": 3, "traces_per_import": 500}),
        patch("sentinel_worker.tasks.import_project_traces.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [
            # scalar_one_or_none → project; scalar_one → count (3); scalars().first() → source
            (project, 3, None),
        ])

        from sentinel_worker.tasks.import_project_traces import _import_project_traces
        result = await _import_project_traces("proj-1", "ws-1", workspace_tier=0)

    assert result["error"] == "quota_exceeded"
    assert result["spans"] == 0
    assert project.status == "error"


@pytest.mark.asyncio
async def test_missing_project_returns_early():
    """When the project row is not found, returns zeros without changing state."""
    with (
        patch("sentinel_worker.tasks.import_project_traces.get_import_limits",
              return_value={"imports_per_week": None, "traces_per_import": None}),
        patch("sentinel_worker.tasks.import_project_traces.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [(None, None, None)])

        from sentinel_worker.tasks.import_project_traces import _import_project_traces
        result = await _import_project_traces("proj-missing", "ws-1", workspace_tier=0)

    assert result["traces"] == 0
    assert result["spans"] == 0


@pytest.mark.asyncio
async def test_no_source_sets_error_status():
    """When no source is configured for the workspace, status → error."""
    project = _make_project()

    with (
        patch("sentinel_worker.tasks.import_project_traces.get_import_limits",
              return_value={"imports_per_week": None, "traces_per_import": None}),
        patch("sentinel_worker.tasks.import_project_traces.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [(project, None, None)])

        from sentinel_worker.tasks.import_project_traces import _import_project_traces
        result = await _import_project_traces("proj-1", "ws-1", workspace_tier=0)

    assert result["error"] == "no_source"
    assert project.status == "error"


@pytest.mark.asyncio
async def test_connector_pull_failure_sets_error_status():
    """When connector.pull_by_window raises, status → error."""
    project = _make_project()
    source = _make_source()

    mock_connector = MagicMock()
    mock_connector.pull_by_window.side_effect = RuntimeError("network timeout")

    with (
        patch("sentinel_worker.tasks.import_project_traces.get_import_limits",
              return_value={"imports_per_week": None, "traces_per_import": None}),
        patch("sentinel_worker.tasks.import_project_traces._get_connector",
              return_value=mock_connector),
        patch("sentinel_worker.tasks.import_project_traces.insert_project_spans"),
        patch("sentinel_worker.tasks.import_project_traces.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [
            (project, None, source),  # first session: load + mark importing
            (project,),               # second session: set error
        ])

        from sentinel_worker.tasks.import_project_traces import _import_project_traces
        result = await _import_project_traces("proj-1", "ws-1", workspace_tier=0)

    assert "error" in result
    assert project.status == "error"


@pytest.mark.asyncio
async def test_import_count_increments_on_reimport():
    """import_count increments each time import runs successfully."""
    span = _make_span()
    project = _make_project(import_count=2)
    source = _make_source()

    mock_connector = MagicMock()
    mock_connector.pull_by_window.return_value = iter([[span]])

    with (
        patch("sentinel_worker.tasks.import_project_traces.get_import_limits",
              return_value={"imports_per_week": None, "traces_per_import": None}),
        patch("sentinel_worker.tasks.import_project_traces._get_connector",
              return_value=mock_connector),
        patch("sentinel_worker.tasks.import_project_traces.insert_project_spans"),
        patch("sentinel_worker.tasks.import_project_traces.get_session") as mock_session_cm,
    ):
        _setup_session_sequence(mock_session_cm, [(project, source), (project,)])

        from sentinel_worker.tasks.import_project_traces import _import_project_traces
        await _import_project_traces("proj-1", "ws-1", workspace_tier=1)

    assert project.import_count == 3


# ---------------------------------------------------------------------------
# Session mock helper
# ---------------------------------------------------------------------------

def _setup_session_sequence(mock_session_cm, call_data: list):
    """
    Build a sequence of async context manager sessions, each returning
    a tuple of objects for scalar_one_or_none / scalar_one / scalars().first().

    call_data is a list of tuples; each tuple maps to one `async with get_session()` call.
    Items in each tuple are returned in order by successive execute() calls.
    """
    sessions = []
    for items in call_data:
        session = _make_mock_session(items)
        sessions.append(session)

    # Cycle through sessions on repeated calls
    call_iter = iter(sessions)

    async def _cm():
        try:
            s = next(call_iter)
        except StopIteration:
            s = _make_mock_session(())
        return s

    mock_session_cm.return_value.__aenter__ = AsyncMock(side_effect=_cm)
    mock_session_cm.return_value.__aexit__ = AsyncMock(return_value=False)

    # Make it work as async context manager directly
    mock_session_cm.side_effect = _build_async_cm_side_effect(sessions)


def _make_mock_session(items: tuple) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.add = MagicMock()

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
        scalars_mock.all.return_value = [value] if value is not None else []
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
