"""Unit tests for the workspace provisioning router."""
from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_api.main import app
from sentinel_pipeline.db.postgres import WorkspaceRow

_ADMIN_KEY = "test-admin-secret"
_ADMIN_HEADERS = {"X-Admin-Key": _ADMIN_KEY}


def _mock_session(scalar=None):
    """Async CM yielding a session whose execute().scalar_one_or_none() returns scalar."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    session.execute = AsyncMock(return_value=result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock(side_effect=lambda row: _fill_row(row))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _fill_row(row: WorkspaceRow) -> None:
    """Simulate DB assigning created_at after flush."""
    from datetime import datetime, timezone
    if row.created_at is None:
        row.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# POST /v1/workspaces — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_workspace_returns_201_with_api_key():
    with (
        patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY),
        patch("sentinel_api.routers.workspaces.get_session", return_value=_mock_session(scalar=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": "acme"}, headers=_ADMIN_HEADERS)

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "acme"
    assert body["tier"] == 0
    assert body["api_key"].startswith("sk-sentinel-")
    assert len(body["api_key"]) > 20
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_create_workspace_with_explicit_tier():
    with (
        patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY),
        patch("sentinel_api.routers.workspaces.get_session", return_value=_mock_session(scalar=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": "pro-customer", "tier": 2}, headers=_ADMIN_HEADERS)

    assert resp.status_code == 201
    assert resp.json()["tier"] == 2


@pytest.mark.asyncio
async def test_api_key_is_unique_per_call():
    """Two calls must produce different keys."""
    keys = []
    for _ in range(2):
        with (
            patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY),
            patch("sentinel_api.routers.workspaces.get_session", return_value=_mock_session(scalar=None)),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
                resp = await c.post("/v1/workspaces", json={"name": "ws"}, headers=_ADMIN_HEADERS)
        keys.append(resp.json()["api_key"])
    assert keys[0] != keys[1]


@pytest.mark.asyncio
async def test_hash_of_api_key_is_stored_not_raw_key():
    """The DB must receive sha256(api_key) in api_key_hash — not the raw key itself."""
    mock_session = _mock_session(scalar=None)
    with (
        patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY),
        patch("sentinel_api.routers.workspaces.get_session", return_value=mock_session),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": "ws"}, headers=_ADMIN_HEADERS)

    raw_key = resp.json()["api_key"]
    expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    # Inspect the WorkspaceRow passed to session.add()
    session = mock_session.__aenter__.return_value
    added_row: WorkspaceRow = session.add.call_args[0][0]
    assert added_row.api_key_hash == expected_hash, "DB must store the hash, not the raw key"
    assert added_row.api_key_hash != raw_key, "Raw key must never be stored in the DB"


# ---------------------------------------------------------------------------
# Auth failures
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_admin_key_returns_401():
    with patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": "ws"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_admin_key_returns_401():
    with patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": "ws"}, headers={"X-Admin-Key": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_unconfigured_admin_key_returns_503():
    """If SENTINEL_ADMIN_KEY is not set, provisioning must be unavailable."""
    with patch("sentinel_api.routers.workspaces.os.environ.get", return_value=""):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": "ws"}, headers=_ADMIN_HEADERS)
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_name_returns_422():
    with patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": ""}, headers=_ADMIN_HEADERS)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_invalid_tier_returns_422():
    with patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces", json={"name": "ws", "tier": 99}, headers=_ADMIN_HEADERS)
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /v1/workspaces/{id}/api-keys — key rotation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rotate_key_returns_201_with_new_key():
    existing = WorkspaceRow(id="ws-1", name="acme", api_key_hash="old-hash", tier=0)
    with (
        patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY),
        patch("sentinel_api.routers.workspaces.get_session", return_value=_mock_session(scalar=existing)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces/ws-1/api-keys", headers=_ADMIN_HEADERS)

    assert resp.status_code == 201
    body = resp.json()
    assert body["workspace_id"] == "ws-1"
    assert body["api_key"].startswith("sk-sentinel-")


@pytest.mark.asyncio
async def test_rotate_key_not_found_returns_404():
    with (
        patch("sentinel_api.routers.workspaces.os.environ.get", return_value=_ADMIN_KEY),
        patch("sentinel_api.routers.workspaces.get_session", return_value=_mock_session(scalar=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/v1/workspaces/missing/api-keys", headers=_ADMIN_HEADERS)

    assert resp.status_code == 404
