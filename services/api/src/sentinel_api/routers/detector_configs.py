"""Detector configs router — workspace-level detector overrides."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from sentinel_pipeline.db.postgres import DetectorConfigRow, WorkspaceRow, get_session

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/detector-configs", tags=["detector-configs"])

_VALID_ACTIONS = {"DISABLED", "OVERRIDE_SEVERITY"}
_VALID_SEVERITIES = {"critical", "high", "warning", "info"}


class DetectorConfigUpsert(BaseModel):
    action: str
    severity: str | None = None


@router.get("")
async def list_detector_configs(
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        result = await session.execute(
            select(DetectorConfigRow).where(DetectorConfigRow.workspace_id == workspace.id)
        )
        rows = result.scalars().all()
    return {"items": [_row_to_dict(r) for r in rows]}


@router.put("/{detector_id}", status_code=200)
async def upsert_detector_config(
    detector_id: str,
    body: DetectorConfigUpsert,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    if body.action not in _VALID_ACTIONS:
        raise HTTPException(
            status_code=400, detail=f"action must be one of {sorted(_VALID_ACTIONS)}"
        )
    if body.action == "OVERRIDE_SEVERITY":
        if not body.severity or body.severity not in _VALID_SEVERITIES:
            raise HTTPException(
                status_code=400,
                detail=f"severity required for OVERRIDE_SEVERITY, must be one of {sorted(_VALID_SEVERITIES)}",
            )

    async with get_session() as session:
        result = await session.execute(
            select(DetectorConfigRow).where(
                DetectorConfigRow.workspace_id == workspace.id,
                DetectorConfigRow.detector_id == detector_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.action = body.action
            row.severity = body.severity if body.action == "OVERRIDE_SEVERITY" else None
        else:
            row = DetectorConfigRow(
                id=str(uuid.uuid4()),
                workspace_id=workspace.id,
                detector_id=detector_id,
                action=body.action,
                severity=body.severity if body.action == "OVERRIDE_SEVERITY" else None,
            )
            session.add(row)
        await session.flush()
        await session.refresh(row)

    return _row_to_dict(row)


@router.delete("/{detector_id}", status_code=204)
async def delete_detector_config(
    detector_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> None:
    async with get_session() as session:
        result = await session.execute(
            delete(DetectorConfigRow)
            .where(
                DetectorConfigRow.workspace_id == workspace.id,
                DetectorConfigRow.detector_id == detector_id,
            )
            .returning(DetectorConfigRow.id)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Detector config not found")


def _row_to_dict(r: DetectorConfigRow) -> dict[str, Any]:
    return {
        "detector_id": r.detector_id,
        "action": r.action,
        "severity": r.severity,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
