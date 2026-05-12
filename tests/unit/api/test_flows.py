"""Unit tests for the flows router."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_pipeline.models.span import SpanKind, SpanStatus
from sentinel_api.main import app
from sentinel_api.routers.flows import _row_to_span
from sentinel_pipeline.db.postgres import WorkspaceRow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ch_row(
    span_id: str,
    kind: str = "chain",       # SpanKind stores lowercase values
    parent: str | None = None,
    start_ms: int = 0,
    end_ms: int = 100,
    input_tokens: int = 0,
    output_tokens: int = 0,
    retry_count: int = 0,
    status: str = "ok",
    model: str | None = None,
    error: str | None = None,
) -> dict:
    """Mimic a ClickHouse row dict returned by fetch_trace_spans."""
    from datetime import timedelta
    return {
        "span_id": span_id,
        "trace_id": "trace-001",
        "parent_span_id": parent,
        "name": span_id,
        "kind": kind,
        "status": status,
        "start_time": _T0 + timedelta(milliseconds=start_ms),
        "end_time": _T0 + timedelta(milliseconds=end_ms),
        "workspace_id": "ws-1",
        "model": model,
        "agent_name": None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "retry_count": retry_count,
        "error_message": error,
        "attributes_json": "{}",
    }


_FAKE_WORKSPACE = WorkspaceRow(id="ws-1", name="test", api_key_hash="x", tier=0)


# ---------------------------------------------------------------------------
# _row_to_span — pure conversion function
# ---------------------------------------------------------------------------

def test_row_to_span_basic():
    row = _ch_row("s1", kind="llm_call", input_tokens=100, output_tokens=50, model="gpt-4o")
    span = _row_to_span(row)
    assert span.span_id == "s1"
    assert span.kind == SpanKind.LLM_CALL
    assert span.input_tokens == 100
    assert span.output_tokens == 50
    assert span.model == "gpt-4o"


def test_row_to_span_empty_strings_become_none():
    row = _ch_row("s2")
    row["parent_span_id"] = ""   # ClickHouse may return "" instead of NULL
    row["model"] = ""
    row["error_message"] = ""
    span = _row_to_span(row)
    assert span.parent_span_id is None
    assert span.model is None
    assert span.error_message is None


def test_row_to_span_all_kinds():
    for kind_str in ("llm_call", "tool_invoke", "chain", "retrieval", "agent_invoke"):
        row = _ch_row("s", kind=kind_str)
        span = _row_to_span(row)
        assert span.kind == SpanKind(kind_str)


def test_row_to_span_error_status():
    row = _ch_row("s_err", kind="chain", status="error", error="timeout")
    span = _row_to_span(row)
    assert span.status == SpanStatus.ERROR
    assert span.error_message == "timeout"


# ---------------------------------------------------------------------------
# GET /v1/flows/{trace_id} — route-level tests
# ---------------------------------------------------------------------------

@pytest.fixture
def two_span_rows():
    """One root CHAIN span + one LLM_CALL child."""
    return [
        _ch_row("root", kind="chain", start_ms=0, end_ms=500),
        _ch_row("llm",  kind="llm_call", parent="root", start_ms=100, end_ms=400,
                input_tokens=200, output_tokens=80),
    ]


@pytest.mark.asyncio
async def test_get_flow_returns_graph_shape(two_span_rows):
    with (
        patch("sentinel_api.routers.flows.fetch_trace_spans", return_value=two_span_rows),
        patch("sentinel_api.middleware.auth.get_session"),
        patch("sentinel_api.routers.flows.get_workspace", return_value=_FAKE_WORKSPACE),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            app.dependency_overrides[
                __import__("sentinel_api.middleware.auth", fromlist=["get_workspace"]).get_workspace
            ] = lambda: _FAKE_WORKSPACE
            resp = await client.get("/v1/flows/trace-001")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["trace_id"] == "trace-001"
    assert len(body["nodes"]) == 2
    assert "edges" in body
    assert "stats" in body
    assert "has_cycle" in body


@pytest.mark.asyncio
async def test_get_flow_stats(two_span_rows):
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.flows.fetch_trace_spans", return_value=two_span_rows):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/flows/trace-001")

    app.dependency_overrides.clear()
    stats = resp.json()["stats"]
    assert stats["span_count"] == 2
    assert stats["llm_calls"] == 1
    assert stats["total_input_tokens"] == 200
    assert stats["total_output_tokens"] == 80


@pytest.mark.asyncio
async def test_get_flow_404_when_no_spans():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.flows.fetch_trace_spans", return_value=[]):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/flows/missing-trace")

    app.dependency_overrides.clear()
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_flow_node_fields(two_span_rows):
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.flows.fetch_trace_spans", return_value=two_span_rows):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/flows/trace-001")

    app.dependency_overrides.clear()
    nodes = {n["id"]: n for n in resp.json()["nodes"]}
    llm = nodes["llm"]
    assert llm["kind"] == "llm_call"
    assert llm["input_tokens"] == 200
    assert llm["output_tokens"] == 80
    assert llm["parent_id"] == "root"
