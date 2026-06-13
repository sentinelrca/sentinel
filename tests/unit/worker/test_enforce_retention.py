"""Unit tests for the enforce_retention Celery task."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from sentinel_pipeline.db.postgres import WorkspaceRow


def _make_workspace(id: str, tier: int) -> WorkspaceRow:
    return WorkspaceRow(id=id, name=f"ws-{id}", api_key_hash="x", tier=tier)


def _mock_session(workspaces: list[WorkspaceRow]):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = workspaces
    session.execute = AsyncMock(return_value=result)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_retention_deletes_spans_for_free_workspace():
    """Free-tier (tier=0) workspace must trigger a delete with a 7-day cutoff."""
    ws = _make_workspace("ws-free", tier=0)
    with (
        patch("sentinel_worker.tasks.enforce_retention.get_session",
              return_value=_mock_session([ws])),
        patch("sentinel_worker.tasks.enforce_retention.delete_spans_older_than") as mock_del,
    ):
        from sentinel_worker.tasks.enforce_retention import _enforce_retention
        result = await _enforce_retention()

    assert result["workspaces_cleaned"] == 1
    assert result["errors"] == 0
    mock_del.assert_called_once()
    call_args = mock_del.call_args
    assert call_args[0][0] == "ws-free"   # workspace_id
    # cutoff must be a valid ISO timestamp (7 days ago)
    cutoff_str = call_args[0][1]
    assert "T" in cutoff_str


@pytest.mark.asyncio
async def test_retention_skips_workspaces_with_unlimited_retention():
    """Paid-tier workspaces with retention_days=None must NOT trigger a delete."""
    ws = _make_workspace("ws-paid", tier=1)

    # Patch get_tier_limits to return None retention for paid tier
    with (
        patch("sentinel_worker.tasks.enforce_retention.get_session",
              return_value=_mock_session([ws])),
        patch("sentinel_worker.tasks.enforce_retention.delete_spans_older_than") as mock_del,
        patch("sentinel_worker.tasks.enforce_retention.get_tier_limits",
              return_value={"retention_days": None, "max_sources": None}),
    ):
        from sentinel_worker.tasks.enforce_retention import _enforce_retention
        result = await _enforce_retention()

    assert result["workspaces_cleaned"] == 0
    mock_del.assert_not_called()


@pytest.mark.asyncio
async def test_retention_handles_mixed_workspaces():
    """Free workspaces get cleaned; paid workspaces are skipped."""
    ws_free   = _make_workspace("ws-free",   tier=0)
    ws_paid   = _make_workspace("ws-paid",   tier=1)
    ws_free2  = _make_workspace("ws-free2",  tier=0)

    with (
        patch("sentinel_worker.tasks.enforce_retention.get_session",
              return_value=_mock_session([ws_free, ws_paid, ws_free2])),
        patch("sentinel_worker.tasks.enforce_retention.delete_spans_older_than") as mock_del,
        patch("sentinel_worker.tasks.enforce_retention.get_tier_limits",
              side_effect=lambda tier: {"retention_days": 7} if tier == 0 else {"retention_days": None}),
    ):
        from sentinel_worker.tasks.enforce_retention import _enforce_retention
        result = await _enforce_retention()

    assert result["workspaces_cleaned"] == 2
    assert result["errors"] == 0
    assert mock_del.call_count == 2
    cleaned_ids = {c[0][0] for c in mock_del.call_args_list}
    assert "ws-free" in cleaned_ids
    assert "ws-free2" in cleaned_ids
    assert "ws-paid" not in cleaned_ids


@pytest.mark.asyncio
async def test_retention_counts_errors_and_continues():
    """An error on one workspace must not stop processing the rest."""
    ws1 = _make_workspace("ws-1", tier=0)
    ws2 = _make_workspace("ws-2", tier=0)

    def _delete_side_effect(workspace_id, cutoff):
        if workspace_id == "ws-1":
            raise RuntimeError("ClickHouse unavailable")

    with (
        patch("sentinel_worker.tasks.enforce_retention.get_session",
              return_value=_mock_session([ws1, ws2])),
        patch("sentinel_worker.tasks.enforce_retention.delete_spans_older_than",
              side_effect=_delete_side_effect),
    ):
        from sentinel_worker.tasks.enforce_retention import _enforce_retention
        result = await _enforce_retention()

    assert result["workspaces_cleaned"] == 1
    assert result["errors"] == 1


@pytest.mark.asyncio
async def test_retention_empty_workspace_list():
    """No workspaces — task completes with zero cleaned."""
    with (
        patch("sentinel_worker.tasks.enforce_retention.get_session",
              return_value=_mock_session([])),
        patch("sentinel_worker.tasks.enforce_retention.delete_spans_older_than") as mock_del,
    ):
        from sentinel_worker.tasks.enforce_retention import _enforce_retention
        result = await _enforce_retention()

    assert result == {"workspaces_cleaned": 0, "errors": 0}
    mock_del.assert_not_called()
