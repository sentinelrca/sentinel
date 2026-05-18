"""Unit tests for sync_source tier gate."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sentinel_pipeline.db.postgres import SourceRow, WorkspaceRow


def _make_source() -> MagicMock:
    source = MagicMock(spec=SourceRow)
    source.kind = "langfuse"
    source.workspace_id = "ws-1"
    source.config_json = {}
    source.last_synced_at = None
    return source


def _make_workspace(tier: int = 0) -> MagicMock:
    ws = MagicMock(spec=WorkspaceRow)
    ws.id = "ws-1"
    ws.tier = tier
    return ws


def _make_mock_session(source, workspace) -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    async def _get(cls, pk):
        if cls is SourceRow:
            return source
        if cls is WorkspaceRow:
            return workspace
        return None

    session.get = _get
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_skips_free_tier_workspace():
    """Free-tier workspaces (tier=0) must not trigger a connector pull."""
    source = _make_source()
    workspace = _make_workspace(tier=0)

    with (
        patch("sentinel_worker.tasks.sync_source.get_session") as mock_gs,
        patch("sentinel_worker.tasks.sync_source._CONNECTOR_MAP") as mock_map,
    ):
        mock_gs.return_value = _make_mock_session(source, workspace)

        from sentinel_worker.tasks.sync_source import _sync_source
        result = await _sync_source("src-1")

    assert result.get("skipped") is True
    assert result["spans"] == 0
    mock_map.get.assert_not_called()


@pytest.mark.asyncio
async def test_sync_skips_when_workspace_not_found():
    """Missing workspace treated like free tier — sync skipped."""
    source = _make_source()

    with (
        patch("sentinel_worker.tasks.sync_source.get_session") as mock_gs,
        patch("sentinel_worker.tasks.sync_source._CONNECTOR_MAP") as mock_map,
    ):
        mock_gs.return_value = _make_mock_session(source, workspace=None)

        from sentinel_worker.tasks.sync_source import _sync_source
        result = await _sync_source("src-1")

    assert result.get("skipped") is True
    mock_map.get.assert_not_called()


@pytest.mark.asyncio
async def test_sync_runs_for_starter_tier():
    """Starter-tier workspaces (tier=1) proceed past the gate to the connector."""
    source = _make_source()
    workspace = _make_workspace(tier=1)

    mock_connector = MagicMock()
    mock_connector.pull.return_value = iter([])

    with (
        patch("sentinel_worker.tasks.sync_source.get_session") as mock_gs,
        patch("sentinel_worker.tasks.sync_source._CONNECTOR_MAP",
              {"langfuse": mock_connector}),
        patch("sentinel_worker.tasks.sync_source.insert_spans"),
    ):
        mock_gs.return_value = _make_mock_session(source, workspace)

        from sentinel_worker.tasks.sync_source import _sync_source
        result = await _sync_source("src-1")

    assert result.get("skipped") is None
    mock_connector.pull.assert_called_once()


@pytest.mark.asyncio
async def test_sync_skips_when_source_not_found():
    """Missing source returns zeros without touching the workspace or connector."""
    with (
        patch("sentinel_worker.tasks.sync_source.get_session") as mock_gs,
    ):
        mock_gs.return_value = _make_mock_session(source=None, workspace=None)

        from sentinel_worker.tasks.sync_source import _sync_source
        result = await _sync_source("src-missing")

    assert result["spans"] == 0
    assert result["traces"] == 0
    assert result.get("skipped") is None
