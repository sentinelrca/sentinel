"""Sources router — manage observability source connections."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from sentinel_pipeline.db.postgres import SourceRow, WorkspaceRow, get_session
from sentinel_pipeline.crypto import decrypt_config, encrypt_config
from sentinel_pipeline.connectors import get_connector
from sentinel_pipeline.limits import get_tier_limits

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/sources", tags=["sources"])

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_celery = Celery(broker=_REDIS_URL, backend=_REDIS_URL)


class SourceCreate(BaseModel):
    kind: str
    config_json: dict[str, Any]


@router.get("")
async def list_sources(
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        result = await session.execute(
            select(SourceRow)
            .where(SourceRow.workspace_id == workspace.id)
            .order_by(SourceRow.created_at.desc())
        )
        rows = result.scalars().all()
    return {"items": [_row_to_dict(r) for r in rows]}


@router.post("", status_code=201)
async def create_source(
    body: SourceCreate,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    connector = get_connector(body.kind)
    if connector is None:
        raise HTTPException(status_code=400, detail=f"Unknown source kind '{body.kind}'")

    ok = await asyncio.to_thread(connector.validate_config, body.config_json)
    if not ok:
        raise HTTPException(status_code=422, detail="Connection test failed — check credentials")

    async with get_session() as session:
        limits = get_tier_limits(workspace.tier)
        max_sources: int | None = limits.get("max_sources")
        if max_sources is not None:
            count_result = await session.execute(
                select(SourceRow).where(SourceRow.workspace_id == workspace.id)
            )
            existing_count = len(count_result.scalars().all())
            if existing_count >= max_sources:
                raise HTTPException(
                    status_code=402,
                    detail=(
                        f"Source limit reached ({existing_count}/{max_sources}). "
                        "Upgrade your plan to connect additional sources."
                    ),
                )

        row = SourceRow(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            kind=body.kind,
            config_json=encrypt_config(body.config_json),
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)

    return _row_to_dict(row)


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(SourceRow).where(
                SourceRow.id == source_id,
                SourceRow.workspace_id == workspace.id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Source not found")
        await session.execute(delete(SourceRow).where(SourceRow.id == source_id))


@router.post("/{source_id}/sync", status_code=202)
async def sync_source_endpoint(
    source_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, str]:
    """Trigger an on-demand sync for a source. Returns the queued task id.

    Tier gating (free-tier workspaces are skipped) is enforced inside the
    sync_source task itself, so this endpoint only verifies ownership.
    """
    async with get_session() as session:
        result = await session.execute(
            select(SourceRow).where(
                SourceRow.id == source_id,
                SourceRow.workspace_id == workspace.id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Source not found")

    task = _celery.send_task("sync_source", args=[source_id])
    return {"task_id": task.id}


def _row_to_dict(r: SourceRow) -> dict[str, Any]:
    config = dict(decrypt_config(r.config_json or {}))
    for key in (
        "secret_key",
        "api_key",
        "token",
        "password",
        "access_token",
        "bearer",
        "auth_token",
        "private_key",
        "client_secret",
    ):
        if key in config:
            config[key] = "***"
    return {
        "id": r.id,
        "kind": r.kind,
        "config": config,
        "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
