"""Rule configs router — workspace-level rule overrides."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from sentinel_pipeline.db.postgres import RuleConfigRow, WorkspaceRow, get_session

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/rule-configs", tags=["rule-configs"])

_VALID_ACTIONS = {"DISABLED", "OVERRIDE_SEVERITY"}
_VALID_SEVERITIES = {"critical", "high", "warning", "info"}


class RuleConfigUpsert(BaseModel):
    action: str
    severity: str | None = None


@router.get("")
async def list_rule_configs(
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        result = await session.execute(
            select(RuleConfigRow).where(RuleConfigRow.workspace_id == workspace.id)
        )
        rows = result.scalars().all()
    return {"items": [_row_to_dict(r) for r in rows]}


@router.put("/{rule_id}", status_code=200)
async def upsert_rule_config(
    rule_id: str,
    body: RuleConfigUpsert,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    if body.action not in _VALID_ACTIONS:
        raise HTTPException(status_code=400, detail=f"action must be one of {sorted(_VALID_ACTIONS)}")
    if body.action == "OVERRIDE_SEVERITY":
        if not body.severity or body.severity not in _VALID_SEVERITIES:
            raise HTTPException(status_code=400, detail=f"severity required for OVERRIDE_SEVERITY, must be one of {sorted(_VALID_SEVERITIES)}")

    async with get_session() as session:
        result = await session.execute(
            select(RuleConfigRow).where(
                RuleConfigRow.workspace_id == workspace.id,
                RuleConfigRow.rule_id == rule_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.action = body.action
            row.severity = body.severity if body.action == "OVERRIDE_SEVERITY" else None
        else:
            row = RuleConfigRow(
                id=str(uuid.uuid4()),
                workspace_id=workspace.id,
                rule_id=rule_id,
                action=body.action,
                severity=body.severity if body.action == "OVERRIDE_SEVERITY" else None,
            )
            session.add(row)
        await session.flush()
        await session.refresh(row)

    return _row_to_dict(row)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule_config(
    rule_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> None:
    async with get_session() as session:
        result = await session.execute(
            delete(RuleConfigRow)
            .where(
                RuleConfigRow.workspace_id == workspace.id,
                RuleConfigRow.rule_id == rule_id,
            )
            .returning(RuleConfigRow.id)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Rule config not found")


def _row_to_dict(r: RuleConfigRow) -> dict[str, Any]:
    return {
        "rule_id": r.rule_id,
        "action": r.action,
        "severity": r.severity,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
