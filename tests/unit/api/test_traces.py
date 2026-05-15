"""Unit tests for the traces router."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_api.main import app
from sentinel_api.middleware.auth import get_workspace as _gw
from sentinel_pipeline.db.postgres import WorkspaceRow

_FAKE_WORKSPACE = WorkspaceRow(id="ws-1", name="test", api_key_hash="x", tier=0)
_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _insight_row(
    trace_id: str = "trace-001",
    rule_id: str = "retry_storm",
    severity: str = "high",
    created_at: datetime | None = None,
):
    row = MagicMock()
    row.id = "ins-1"
    row.trace_id = trace_id
    row.rule_id = rule_id
    row.severity = severity
    row.title = "Test insight"
    row.detail = "detail"
    row.recommendation = "rec"
    row.affected_span_ids = ["s1"]
    row.evidence = {}
    row.status = "open"
    row.created_at = created_at or _T0
    return row


def _mock_session_group(groups: list):
    """Return an async context manager whose execute() yields group results."""
    session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = len(groups)
    rows_result = MagicMock()
    rows_result.all.return_value = groups
    session.execute = AsyncMock(side_effect=[count_result, rows_result])
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session_insights(rows: list):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _group(
    trace_id: str,
    insight_count: int,
    rule_ids: list[str],
    severities: list[str],
    latest: datetime | None = None,
):
    g = MagicMock()
    g.trace_id = trace_id
    g.insight_count = insight_count
    g.rule_ids = rule_ids
    g.severities = severities
    g.latest_insight_at = latest or _T0
    return g


# ---------------------------------------------------------------------------
# GET /v1/traces
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_traces_empty():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_group([])):
        with patch("sentinel_api.routers.traces.fetch_trace_stats_batch", return_value={}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_traces_returns_worst_severity():
    groups = [_group("t1", 2, ["retry_storm", "latency_spike"], ["warning", "high"])]
    stats = {"t1": {"span_count": 10, "llm_calls": 3, "total_ms": 1200}}
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_group(groups)):
        with patch("sentinel_api.routers.traces.fetch_trace_stats_batch", return_value=stats):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["trace_id"] == "t1"
    assert item["worst_severity"] == "high"
    assert item["insight_count"] == 2
    assert set(item["rule_ids"]) == {"retry_storm", "latency_spike"}


@pytest.mark.asyncio
async def test_list_traces_span_stats_included():
    groups = [_group("t2", 1, ["agent_loop"], ["critical"])]
    stats = {"t2": {"span_count": 19, "llm_calls": 6, "total_ms": 5600}}
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_group(groups)):
        with patch("sentinel_api.routers.traces.fetch_trace_stats_batch", return_value=stats):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    item = resp.json()["items"][0]
    assert item["span_count"] == 19
    assert item["llm_calls"] == 6
    assert item["total_ms"] == 5600


@pytest.mark.asyncio
async def test_list_traces_missing_stats_defaults_to_zero():
    groups = [_group("t3", 1, ["sequential_tools"], ["info"])]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_group(groups)):
        with patch("sentinel_api.routers.traces.fetch_trace_stats_batch", return_value={}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    item = resp.json()["items"][0]
    assert item["span_count"] == 0
    assert item["llm_calls"] == 0
    assert item["total_ms"] == 0


@pytest.mark.asyncio
async def test_list_traces_worst_severity_critical_beats_all():
    groups = [_group("t4", 3, ["a", "b", "c"], ["info", "warning", "critical"])]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_group(groups)):
        with patch("sentinel_api.routers.traces.fetch_trace_stats_batch", return_value={}):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    assert resp.json()["items"][0]["worst_severity"] == "critical"


# ---------------------------------------------------------------------------
# GET /v1/traces/{trace_id}/insights
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_trace_insights_returns_all():
    rows = [_insight_row("t5", "retry_storm", "high"), _insight_row("t5", "latency_spike", "warning")]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_insights(rows)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces/t5/insights")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == "t5"
    assert body["total"] == 2
    assert {i["rule_id"] for i in body["items"]} == {"retry_storm", "latency_spike"}


@pytest.mark.asyncio
async def test_get_trace_insights_empty():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_insights([])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces/unknown/insights")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
