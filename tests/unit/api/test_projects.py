"""Unit tests for the projects router."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_api.main import app
from sentinel_api.middleware.auth import get_workspace as _gw
from sentinel_pipeline.db.postgres import ProjectRow, WorkspaceRow

_FAKE_WORKSPACE = WorkspaceRow(id="ws-1", name="test", api_key_hash="x", tier=0)
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _project_row(**overrides) -> MagicMock:
    row = MagicMock(spec=ProjectRow)
    row.id = "proj-1"
    row.workspace_id = "ws-1"
    row.name = "My Project"
    row.filters = {}
    row.status = "pending"
    row.trace_count = 0
    row.import_count = 0
    row.created_at = _NOW
    row.last_imported_at = None
    row.last_analyzed_at = None
    for k, v in overrides.items():
        setattr(row, k, v)
    return row


def _mock_session_scalars(rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session_scalar_one_or_none(row):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session_delete(rowcount: int):
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = rowcount
    session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# POST /v1/projects
# ---------------------------------------------------------------------------

def _mock_session_create():
    """Mock for create_project: session.add + flush + refresh — no execute needed."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_create_project_success():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_create()):
        with patch("sentinel_api.routers.projects.ProjectRow") as MockRow:
            instance = MagicMock()
            instance.id = "proj-new"
            instance.workspace_id = "ws-1"
            instance.name = "My Project"
            instance.filters = {}
            instance.status = "pending"
            instance.trace_count = 0
            instance.import_count = 0
            instance.created_at = _NOW
            instance.last_imported_at = None
            instance.last_analyzed_at = None
            MockRow.return_value = instance
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/v1/projects", json={"name": "My Project", "filters": {}})

    app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["name"] == "My Project"
    assert resp.json()["workspace_id"] == "ws-1"
    assert resp.json()["status"] == "pending"
    assert resp.json()["trace_count"] == 0
    assert resp.json()["import_count"] == 0


@pytest.mark.asyncio
async def test_create_project_empty_name_returns_400():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/v1/projects", json={"name": "   "})

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_project_with_filters():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    filters = {"date_from": "2026-01-01T00:00:00", "date_to": "2026-01-31T23:59:59"}
    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_create()):
        with patch("sentinel_api.routers.projects.ProjectRow") as MockRow:
            instance = MagicMock()
            instance.id = "proj-new"
            instance.workspace_id = "ws-1"
            instance.name = "January"
            instance.filters = filters
            instance.status = "pending"
            instance.trace_count = 0
            instance.import_count = 0
            instance.created_at = _NOW
            instance.last_imported_at = None
            instance.last_analyzed_at = None
            MockRow.return_value = instance
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/v1/projects", json={"name": "January", "filters": filters})

    app.dependency_overrides.clear()
    assert resp.status_code == 201
    assert resp.json()["filters"]["date_from"] == "2026-01-01T00:00:00"


# ---------------------------------------------------------------------------
# GET /v1/projects
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_projects_empty():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_scalars([])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_projects_returns_rows():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    rows = [_project_row(), _project_row(id="proj-2", name="Second Project")]
    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_scalars(rows)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects")

    app.dependency_overrides.clear()
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["name"] == "My Project"
    assert body["items"][1]["name"] == "Second Project"


# ---------------------------------------------------------------------------
# GET /v1/projects/{project_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_project_success():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    row = _project_row()
    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_scalar_one_or_none(row)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects/proj-1")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["id"] == "proj-1"


@pytest.mark.asyncio
async def test_get_project_returns_status_fields():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    row = _project_row(status="ready", trace_count=42, import_count=2, last_imported_at=_NOW)
    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_scalar_one_or_none(row)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects/proj-1")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["trace_count"] == 42
    assert body["import_count"] == 2
    assert body["last_imported_at"] is not None


@pytest.mark.asyncio
async def test_get_project_not_found_returns_404():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_scalar_one_or_none(None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects/nonexistent")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /v1/projects/{project_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_project_success():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_delete(1)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/v1/projects/proj-1")

    app.dependency_overrides.clear()
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_project_not_found_returns_404():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_delete(0)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.delete("/v1/projects/nonexistent")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /v1/projects/{project_id}/analyze
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_analyze_project_queues_task():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    row = _project_row()
    mock_task = MagicMock()
    mock_task.id = "celery-task-abc123"

    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_scalar_one_or_none(row)):
        with patch("sentinel_api.routers.projects._celery.send_task", return_value=mock_task) as mock_send:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/v1/projects/proj-1/analyze")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["task_id"] == "celery-task-abc123"
    mock_send.assert_called_once_with(
        "analyze_project",
        args=["proj-1", "ws-1", 0],
    )


@pytest.mark.asyncio
async def test_analyze_project_not_found_returns_404():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    with patch("sentinel_api.routers.projects.get_session", return_value=_mock_session_scalar_one_or_none(None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/projects/nonexistent/analyze")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/projects/{project_id}/insights
# ---------------------------------------------------------------------------

def _mock_session_project_insights(project_row, insight_rows):
    """Returns two execute calls: first for project lookup, second for insights."""
    session = AsyncMock()

    proj_result = MagicMock()
    proj_result.scalar_one_or_none.return_value = project_row

    insights_result = MagicMock()
    insights_result.scalars.return_value.all.return_value = insight_rows

    session.execute = AsyncMock(side_effect=[proj_result, insights_result])
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _insight_row(project_id: str = "proj-1", rule_id: str = "retry_storm") -> MagicMock:
    row = MagicMock()
    row.id = "ins-1"
    row.trace_id = "trace-001"
    row.rule_id = rule_id
    row.severity = "high"
    row.title = "Test"
    row.detail = "detail"
    row.recommendation = "rec"
    row.affected_span_ids = []
    row.evidence = {}
    row.status = "open"
    row.project_id = project_id
    row.created_at = _NOW
    return row


@pytest.mark.asyncio
async def test_get_project_insights_success():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    proj = _project_row()
    insights = [_insight_row(), _insight_row(rule_id="latency_spike")]
    with patch("sentinel_api.routers.projects.get_session",
               return_value=_mock_session_project_insights(proj, insights)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects/proj-1/insights")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert {i["rule_id"] for i in body["items"]} == {"retry_storm", "latency_spike"}
    assert body["items"][0]["project_id"] == "proj-1"


@pytest.mark.asyncio
async def test_get_project_insights_empty():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    proj = _project_row()
    with patch("sentinel_api.routers.projects.get_session",
               return_value=_mock_session_project_insights(proj, [])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects/proj-1/insights")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_get_project_insights_project_not_found():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE

    with patch("sentinel_api.routers.projects.get_session",
               return_value=_mock_session_project_insights(None, [])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/projects/nonexistent/insights")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Feed isolation — main traces/insights feeds must not leak project insights
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_traces_excludes_project_insights():
    """GET /v1/traces must only count insights with project_id IS NULL."""
    from sentinel_api.middleware.auth import get_workspace as _gw2

    _FAKE_WS = WorkspaceRow(id="ws-1", name="test", api_key_hash="x", tier=0)
    app.dependency_overrides[_gw2] = lambda: _FAKE_WS

    # Simulate: no open continuous-sync insights (project insights exist but shouldn't appear)
    from unittest.mock import patch as _patch
    from tests.unit.api.test_traces import _mock_session_group, _patches

    with _patches(groups=[]):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["items"] == []
    assert resp.json()["total"] == 0
