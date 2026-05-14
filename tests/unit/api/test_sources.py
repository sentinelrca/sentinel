"""Unit tests for the sources router."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_api.main import app
from sentinel_api.routers.sources import _row_to_dict
from sentinel_pipeline.db.postgres import SourceRow, WorkspaceRow

_FAKE_WORKSPACE = WorkspaceRow(id="ws-1", name="test", api_key_hash="x", tier=0)
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# _row_to_dict — secret redaction (critical security property)
# ---------------------------------------------------------------------------

def _source_row(kind: str, config: dict) -> SourceRow:
    return SourceRow(
        id="src-1",
        workspace_id="ws-1",
        kind=kind,
        config_json=config,
        last_synced_at=None,
        created_at=_NOW,
    )


def test_redacts_langfuse_secret_key():
    row = _source_row("langfuse", {"public_key": "pk-lf-abc", "secret_key": "sk-lf-secret"})
    d = _row_to_dict(row)
    assert d["config"]["secret_key"] == "***"
    assert d["config"]["public_key"] == "pk-lf-abc"  # non-secret preserved


def test_redacts_langsmith_api_key():
    row = _source_row("langsmith", {"api_key": "lsv2_pt_super_secret", "project_name": "my-proj"})
    d = _row_to_dict(row)
    assert d["config"]["api_key"] == "***"
    assert d["config"]["project_name"] == "my-proj"


def test_redacts_generic_password_and_token():
    row = _source_row("custom", {"token": "tok123", "password": "pass456", "host": "https://x.com"})
    d = _row_to_dict(row)
    assert d["config"]["token"] == "***"
    assert d["config"]["password"] == "***"
    assert d["config"]["host"] == "https://x.com"


def test_no_redaction_needed_leaves_config_intact():
    row = _source_row("langfuse", {"public_key": "pk-lf-abc", "host": "https://cloud.langfuse.com"})
    d = _row_to_dict(row)
    assert d["config"] == {"public_key": "pk-lf-abc", "host": "https://cloud.langfuse.com"}


def test_row_to_dict_shape():
    row = _source_row("langfuse", {})
    d = _row_to_dict(row)
    assert d["id"] == "src-1"
    assert d["kind"] == "langfuse"
    assert d["created_at"] == _NOW.isoformat()
    assert d["last_synced_at"] is None


# ---------------------------------------------------------------------------
# Route-level tests
# ---------------------------------------------------------------------------

def _mock_session(rows=None):
    """Return an async context-manager that yields a mock session."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = rows or []
    mock_session.execute = AsyncMock(return_value=mock_result)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_list_sources_empty():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.sources.get_session", return_value=_mock_session([])):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/sources")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


@pytest.mark.asyncio
async def test_create_source_unknown_kind_returns_400():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/v1/sources",
            json={"kind": "arize", "config_json": {}},
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 400
    assert "Unknown source kind" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_source_invalid_credentials_returns_422():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.sources._CONNECTORS", {
        "langfuse": MagicMock(validate_config=MagicMock(return_value=False))
    }):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/sources",
                json={"kind": "langfuse", "config_json": {"public_key": "bad", "secret_key": "bad"}},
            )

    app.dependency_overrides.clear()
    assert resp.status_code == 422
    assert "Connection test failed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_source_not_found_returns_404():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)

    with patch("sentinel_api.routers.sources.get_session", return_value=cm):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/v1/sources/nonexistent-id")

    app.dependency_overrides.clear()
    assert resp.status_code == 404
