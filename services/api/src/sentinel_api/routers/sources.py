"""Sources router — manage observability source connections."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from sentinel_pipeline.db.postgres import SourceRow, WorkspaceRow, get_session
from sentinel_connectors.langfuse import LangfuseConnector
from sentinel_connectors.langsmith import LangSmithConnector

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/sources", tags=["sources"])

_CONNECTORS = {
    "langfuse":   LangfuseConnector(),
    "langsmith":  LangSmithConnector(),
}


class SourceCreate(BaseModel):
    kind:        str
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
    connector = _CONNECTORS.get(body.kind)
    if connector is None:
        raise HTTPException(status_code=400, detail=f"Unknown source kind '{body.kind}'")

    if not connector.validate_config(body.config_json):
        raise HTTPException(status_code=422, detail="Connection test failed — check credentials")

    async with get_session() as session:
        row = SourceRow(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            kind=body.kind,
            config_json=body.config_json,
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
        await session.execute(
            delete(SourceRow).where(SourceRow.id == source_id)
        )


def _row_to_dict(r: SourceRow) -> dict[str, Any]:
    config = dict(r.config_json or {})
    # Redact secrets before sending to client
    for key in ("secret_key", "api_key", "token", "password"):
        if key in config:
            config[key] = "***"
    return {
        "id": r.id,
        "kind": r.kind,
        "config": config,
        "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
