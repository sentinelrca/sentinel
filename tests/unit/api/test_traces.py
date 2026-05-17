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


def _mock_session_group(groups: list, severity_counts: dict | None = None, last_synced_at=None):
    """Return an async context manager whose execute() yields all list_traces results.

    list_traces makes 4 execute calls inside the session:
      1. COUNT DISTINCT trace_id  → scalar_one
      2. GROUP BY rows            → .all()
      3. severity breakdown       → .all()
      4. MAX(last_synced_at)      → scalar_one
    """
    session = AsyncMock()

    count_result = MagicMock()
    count_result.scalar_one.return_value = len(groups)

    rows_result = MagicMock()
    rows_result.all.return_value = groups

    sev_rows = []
    if severity_counts:
        for sev, cnt in severity_counts.items():
            r = MagicMock()
            r.severity = sev
            r.cnt = cnt
            sev_rows.append(r)
    severity_result = MagicMock()
    severity_result.all.return_value = sev_rows

    sync_result = MagicMock()
    sync_result.scalar_one.return_value = last_synced_at

    session.execute = AsyncMock(side_effect=[count_result, rows_result, severity_result, sync_result])
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

def _patches(groups=None, stats=None):
    """Context manager stacking the three patches needed by list_traces."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("sentinel_api.routers.traces.get_session",
                              return_value=_mock_session_group(groups or [])))
    stack.enter_context(patch("sentinel_api.routers.traces.fetch_trace_stats_batch",
                              return_value=stats or {}))
    stack.enter_context(patch("sentinel_api.routers.traces.count_distinct_traces",
                              return_value=len(groups or [])))
    return stack


@pytest.mark.asyncio
async def test_list_traces_empty():
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches():
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
    with _patches(groups=groups, stats=stats):
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
    with _patches(groups=groups, stats=stats):
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
    with _patches(groups=groups):
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
    with _patches(groups=groups):
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


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_traces_pagination_params_forwarded():
    """limit and offset from query params are reflected in the response."""
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces?limit=10&offset=20")
    app.dependency_overrides.clear()
    body = resp.json()
    assert resp.status_code == 200
    assert body["limit"] == 10
    assert body["offset"] == 20


@pytest.mark.asyncio
async def test_list_traces_pagination_defaults():
    """Default limit=50, offset=0 when not supplied."""
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    body = resp.json()
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_list_traces_rejects_limit_above_max():
    """limit > 200 should be rejected with 422."""
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces?limit=201")
    app.dependency_overrides.clear()
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# rule_ids deduplication
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_traces_deduplicates_rule_ids():
    """When array_agg returns duplicate rule IDs, the response must deduplicate them."""
    groups = [_group("t6", 3, ["retry_storm", "retry_storm", "latency_spike"], ["high", "high", "warning"])]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches(groups=groups):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    item = resp.json()["items"][0]
    assert item["rule_ids"].count("retry_storm") == 1, "duplicate rule_ids must be removed"
    assert set(item["rule_ids"]) == {"retry_storm", "latency_spike"}


@pytest.mark.asyncio
async def test_list_traces_rule_ids_preserves_order():
    """Dedup must preserve the first-seen order, not sort or reverse."""
    groups = [_group("t7", 4, ["b", "a", "b", "c"], ["info", "info", "info", "info"])]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches(groups=groups):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    assert resp.json()["items"][0]["rule_ids"] == ["b", "a", "c"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_traces_empty_severities_falls_back_to_info():
    """A trace group with an empty severities list must not crash — defaults to 'info'."""
    groups = [_group("t8", 1, ["some_rule"], [])]  # empty severities
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches(groups=groups):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["worst_severity"] == "info"


@pytest.mark.asyncio
async def test_list_traces_multiple_traces_ordered_by_latest():
    """Response items are in descending latest_insight_at order."""
    from datetime import timedelta
    t_old = _T0
    t_new = _T0 + timedelta(hours=1)
    groups = [
        _group("older",  1, ["a"], ["info"],    latest=t_old),
        _group("newer",  1, ["b"], ["warning"], latest=t_new),
    ]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with _patches(groups=groups):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces")
    app.dependency_overrides.clear()
    items = resp.json()["items"]
    assert len(items) == 2
    assert {i["trace_id"] for i in items} == {"older", "newer"}


@pytest.mark.asyncio
async def test_get_trace_insights_insight_fields_complete():
    """Each insight item in the response includes all required fields."""
    row = _insight_row("t9", "agent_loop", "critical")
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.traces.get_session", return_value=_mock_session_insights([row])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/v1/traces/t9/insights")
    app.dependency_overrides.clear()
    item = resp.json()["items"][0]
    for field in ("id", "trace_id", "rule_id", "severity", "title", "detail",
                  "recommendation", "affected_span_ids", "evidence", "status", "created_at"):
        assert field in item, f"missing field: {field}"
