"""Insights router — list and retrieve insights for a workspace."""
from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from sentinel_pipeline.db.postgres import InsightRow, WorkspaceRow, get_session
from sentinel_pipeline.models.insight import Severity

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("")
async def list_insights(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    severity: str | None = Query(None),
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        q = select(InsightRow).where(InsightRow.workspace_id == workspace.id)
        if severity:
            q = q.where(InsightRow.severity == severity)
        q = q.order_by(InsightRow.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(q)
        rows = result.scalars().all()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{insight_id}")
async def get_insight(
    insight_id: uuid.UUID,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        result = await session.execute(
            select(InsightRow).where(
                InsightRow.id == insight_id,
                InsightRow.workspace_id == workspace.id,
            )
        )
        row = result.scalar_one_or_none()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Insight not found")
    return _row_to_dict(row)


def _row_to_dict(r: InsightRow) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "trace_id": r.trace_id,
        "rule_id": r.rule_id,
        "severity": r.severity,
        "title": r.title,
        "recommendation": r.recommendation,
        "evidence": r.evidence,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
