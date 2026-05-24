"""Unit tests for the insights router."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_api.main import app
from sentinel_api.routers.insights import _row_to_dict
from sentinel_pipeline.db.postgres import InsightRow, WorkspaceRow

_FAKE_WORKSPACE = WorkspaceRow(id="ws-1", name="test", api_key_hash="x", tier=0)
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _row_to_dict — field completeness
# ---------------------------------------------------------------------------

def _insight_row(**overrides) -> InsightRow:
    defaults = dict(
        id="ins-1",
        workspace_id="ws-1",
        trace_id="trace-abc",
        detector_id="agent_loop",
        severity="HIGH",
        title="Agent loop detected",
        detail="PlannerAgent invoked 4 times",
        recommendation="Add a loop guard",
        affected_span_ids=["s1", "s2"],
        evidence={"loop_count": 4},
        status="open",
        created_at=_NOW,
    )
    return InsightRow(**{**defaults, **overrides})


def test_row_to_dict_includes_all_fields():
    d = _row_to_dict(_insight_row())
    assert d["id"] == "ins-1"
    assert d["trace_id"] == "trace-abc"
    assert d["detector_id"] == "agent_loop"
    assert d["severity"] == "HIGH"
    assert d["title"] == "Agent loop detected"
    assert d["detail"] == "PlannerAgent invoked 4 times"
    assert d["recommendation"] == "Add a loop guard"
    assert d["affected_span_ids"] == ["s1", "s2"]
    assert d["evidence"] == {"loop_count": 4}
    assert d["status"] == "open"
    assert d["created_at"] == _NOW.isoformat()


def test_row_to_dict_null_affected_span_ids_becomes_empty_list():
    d = _row_to_dict(_insight_row(affected_span_ids=None))
    assert d["affected_span_ids"] == []


def test_row_to_dict_null_created_at():
    d = _row_to_dict(_insight_row(created_at=None))
    assert d["created_at"] is None


def test_row_to_dict_all_severities():
    for severity in ("CRITICAL", "HIGH", "WARNING", "INFO"):
        d = _row_to_dict(_insight_row(severity=severity))
        assert d["severity"] == severity


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------

def _mock_session_with_insights(rows, total=None):
    """Mock get_session to return given InsightRows and optional count."""
    if total is None:
        total = len(rows)

    mock_session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = total

    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = rows

    mock_session.execute = AsyncMock(side_effect=[count_result, rows_result])

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_list_insights_response_shape():
    from sentinel_api.middleware.auth import get_workspace as _gw

    rows = [_insight_row()]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=_mock_session_with_insights(rows, total=1)):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/insights")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert len(body["items"]) == 1


@pytest.mark.asyncio
async def test_list_insights_item_includes_detail():
    from sentinel_api.middleware.auth import get_workspace as _gw

    rows = [_insight_row(detail="PlannerAgent invoked 4 times")]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=_mock_session_with_insights(rows)):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/insights")

    app.dependency_overrides.clear()
    item = resp.json()["items"][0]
    assert item["detail"] == "PlannerAgent invoked 4 times"


@pytest.mark.asyncio
async def test_list_insights_empty():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=_mock_session_with_insights([], total=0)):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/insights")

    app.dependency_overrides.clear()
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_get_insight_by_id():
    from sentinel_api.middleware.auth import get_workspace as _gw

    row = _insight_row()
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    mock_session.execute = AsyncMock(return_value=mock_result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=cm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/insights/ins-1")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["id"] == "ins-1"
    assert resp.json()["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_get_insight_not_found_returns_404():
    from sentinel_api.middleware.auth import get_workspace as _gw

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=cm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/insights/does-not-exist")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_insights_pagination_params():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=_mock_session_with_insights([], total=0)):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/insights?limit=10&offset=20")

    app.dependency_overrides.clear()
    body = resp.json()
    assert body["limit"] == 10
    assert body["offset"] == 20


# ---------------------------------------------------------------------------
# PATCH /v1/insights/{id}
# ---------------------------------------------------------------------------

def _mock_session_patch(row):
    mock_session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    mock_session.execute = AsyncMock(return_value=result)
    mock_session.flush = AsyncMock()
    mock_session.refresh = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_patch_insight_status_ignored():
    from sentinel_api.middleware.auth import get_workspace as _gw

    row = _insight_row(status="open")
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=_mock_session_patch(row)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/v1/insights/ins-1", json={"status": "ignored"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert row.status == "ignored"


@pytest.mark.asyncio
async def test_patch_insight_severity_override():
    from sentinel_api.middleware.auth import get_workspace as _gw

    row = _insight_row(severity="high")
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=_mock_session_patch(row)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/v1/insights/ins-1", json={"severity": "warning"})

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert row.severity == "warning"


@pytest.mark.asyncio
async def test_patch_insight_invalid_status_returns_400():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/v1/insights/ins-1", json={"status": "resolved"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_insight_invalid_severity_returns_400():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.patch("/v1/insights/ins-1", json={"severity": "extreme"})

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_patch_insight_not_found_returns_404():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.insights.get_session", return_value=_mock_session_patch(None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch("/v1/insights/missing", json={"status": "ignored"})

    app.dependency_overrides.clear()
    assert resp.status_code == 404
