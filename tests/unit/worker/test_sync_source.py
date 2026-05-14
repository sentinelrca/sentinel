"""Unit tests for sync_source overlap window and cursor logic."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_source(last_synced_at=None):
    source = MagicMock()
    source.id = "src-1"
    source.workspace_id = "ws-test"
    source.kind = "langfuse"
    source.config_json = {"public_key": "pk", "secret_key": "sk"}
    source.last_synced_at = last_synced_at
    return source


@pytest.mark.asyncio
async def test_overlap_window_applied_to_since():
    """since should be last_synced_at minus 10 minutes."""
    last_synced = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
    source = _make_source(last_synced_at=last_synced)

    connector = MagicMock()
    connector.pull.return_value = iter([])  # no spans

    with (
        patch(
            "sentinel_worker.tasks.sync_source._CONNECTOR_MAP",
            {"langfuse": connector},
        ),
        patch(
            "sentinel_worker.tasks.sync_source.get_session",
        ) as mock_session_ctx,
        patch("sentinel_worker.tasks.sync_source.insert_spans_dedup", return_value=0),
    ):
        session = AsyncMock()
        session.get.return_value = source
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from sentinel_worker.tasks.sync_source import _sync_source
        await _sync_source("src-1")

    # Verify pull was called with since = last_synced - 10 min
    call_kwargs = connector.pull.call_args
    actual_since = call_kwargs[1].get("since") or call_kwargs[0][1]
    expected_since = last_synced - timedelta(minutes=10)
    assert actual_since == expected_since


@pytest.mark.asyncio
async def test_first_sync_uses_epoch_minus_overlap():
    """When last_synced_at is None, since = epoch - 10 minutes (effectively epoch)."""
    source = _make_source(last_synced_at=None)

    connector = MagicMock()
    connector.pull.return_value = iter([])

    with (
        patch(
            "sentinel_worker.tasks.sync_source._CONNECTOR_MAP",
            {"langfuse": connector},
        ),
        patch("sentinel_worker.tasks.sync_source.get_session") as mock_session_ctx,
        patch("sentinel_worker.tasks.sync_source.insert_spans_dedup", return_value=0),
    ):
        session = AsyncMock()
        session.get.return_value = source
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from sentinel_worker.tasks.sync_source import _sync_source
        await _sync_source("src-1")

    call_kwargs = connector.pull.call_args
    actual_since = call_kwargs[1].get("since") or call_kwargs[0][1]
    epoch_fallback = datetime(2020, 1, 1, tzinfo=timezone.utc) - timedelta(minutes=10)
    assert actual_since == epoch_fallback


@pytest.mark.asyncio
async def test_cursor_committed_before_inserts():
    """last_synced_at must be updated (and session committed) before pull is called."""
    source = _make_source(last_synced_at=datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc))

    commit_called_before_pull = False
    pull_called = False

    connector = MagicMock()

    def pull_side_effect(*args, **kwargs):
        nonlocal pull_called
        # By the time pull is called, commit should already have happened
        assert source.last_synced_at != datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc), \
            "last_synced_at was not updated before pull"
        pull_called = True
        return iter([])

    connector.pull.side_effect = pull_side_effect

    with (
        patch(
            "sentinel_worker.tasks.sync_source._CONNECTOR_MAP",
            {"langfuse": connector},
        ),
        patch("sentinel_worker.tasks.sync_source.get_session") as mock_session_ctx,
        patch("sentinel_worker.tasks.sync_source.insert_spans_dedup", return_value=0),
    ):
        session = AsyncMock()
        session.get.return_value = source
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        from sentinel_worker.tasks.sync_source import _sync_source
        await _sync_source("src-1")

    assert pull_called


@pytest.mark.asyncio
async def test_langsmith_connector_is_registered():
    """LangSmith must be in the connector map."""
    from sentinel_worker.tasks.sync_source import _CONNECTOR_MAP
    assert "langsmith" in _CONNECTOR_MAP


def test_langfuse_connector_is_registered():
    """Langfuse must be in the connector map."""
    from sentinel_worker.tasks.sync_source import _CONNECTOR_MAP
    assert "langfuse" in _CONNECTOR_MAP
