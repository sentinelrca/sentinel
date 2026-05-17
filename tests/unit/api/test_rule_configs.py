"""Unit tests for the rule_configs router."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from sentinel_api.main import app
from sentinel_pipeline.db.postgres import RuleConfigRow, WorkspaceRow

_FAKE_WORKSPACE = WorkspaceRow(id="ws-1", name="test", api_key_hash="x", tier=0)
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _cfg_row(**overrides) -> RuleConfigRow:
    defaults = dict(
        id="cfg-1",
        workspace_id="ws-1",
        rule_id="agent_loop",
        action="DISABLED",
        severity=None,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return RuleConfigRow(**{**defaults, **overrides})


def _mock_session_empty():
    mock_session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session_with_rows(rows):
    mock_session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    mock_session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _mock_session_returning(row):
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


# ---------------------------------------------------------------------------
# GET /v1/rule-configs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_rule_configs_empty():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.rule_configs.get_session", return_value=_mock_session_empty()):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/rule-configs")

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


@pytest.mark.asyncio
async def test_list_rule_configs_returns_rows():
    from sentinel_api.middleware.auth import get_workspace as _gw

    rows = [_cfg_row(), _cfg_row(id="cfg-2", rule_id="sequential_tools", action="OVERRIDE_SEVERITY", severity="info")]
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.rule_configs.get_session", return_value=_mock_session_with_rows(rows)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/rule-configs")

    app.dependency_overrides.clear()
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["rule_id"] == "agent_loop"
    assert body["items"][0]["action"] == "DISABLED"
    assert body["items"][1]["action"] == "OVERRIDE_SEVERITY"
    assert body["items"][1]["severity"] == "info"


# ---------------------------------------------------------------------------
# PUT /v1/rule-configs/{rule_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_rule_config_disabled_updates_existing():
    from sentinel_api.middleware.auth import get_workspace as _gw

    existing = _cfg_row(action="OVERRIDE_SEVERITY", severity="warning")
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.rule_configs.get_session", return_value=_mock_session_returning(existing)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/v1/rule-configs/agent_loop",
                json={"action": "DISABLED"},
            )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert existing.action == "DISABLED"
    assert existing.severity is None


@pytest.mark.asyncio
async def test_put_rule_config_override_severity():
    from sentinel_api.middleware.auth import get_workspace as _gw

    existing = _cfg_row(action="OVERRIDE_SEVERITY", severity="warning")
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.rule_configs.get_session", return_value=_mock_session_returning(existing)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/v1/rule-configs/agent_loop",
                json={"action": "OVERRIDE_SEVERITY", "severity": "info"},
            )

    app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["action"] == "OVERRIDE_SEVERITY"
    assert resp.json()["severity"] == "info"


@pytest.mark.asyncio
async def test_put_rule_config_invalid_action_returns_400():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/v1/rule-configs/agent_loop",
            json={"action": "INVALID"},
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_rule_config_override_severity_without_severity_returns_400():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/v1/rule-configs/agent_loop",
            json={"action": "OVERRIDE_SEVERITY"},
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_rule_config_invalid_severity_returns_400():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.put(
            "/v1/rule-configs/agent_loop",
            json={"action": "OVERRIDE_SEVERITY", "severity": "extreme"},
        )

    app.dependency_overrides.clear()
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /v1/rule-configs/{rule_id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_rule_config_success():
    from sentinel_api.middleware.auth import get_workspace as _gw

    existing = _cfg_row()
    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.rule_configs.get_session", return_value=_mock_session_returning(existing)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/v1/rule-configs/agent_loop")

    app.dependency_overrides.clear()
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_delete_rule_config_not_found_returns_404():
    from sentinel_api.middleware.auth import get_workspace as _gw

    app.dependency_overrides[_gw] = lambda: _FAKE_WORKSPACE
    with patch("sentinel_api.routers.rule_configs.get_session", return_value=_mock_session_returning(None)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/v1/rule-configs/nonexistent")

    app.dependency_overrides.clear()
    assert resp.status_code == 404
