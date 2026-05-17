"""Insights router — list and retrieve insights for a workspace."""
from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from sentinel_pipeline.db.postgres import InsightRow, WorkspaceRow, get_session

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/insights", tags=["insights"])

_VALID_STATUSES = {"open", "ignored"}
_VALID_SEVERITIES = {"critical", "high", "warning", "info"}


class InsightPatch(BaseModel):
    status: str | None = None
    severity: str | None = None


@router.get("")
async def list_insights(
    limit:           int = Query(50, le=200),
    offset:          int = Query(0, ge=0),
    severity:        str | None = Query(None),
    rule_id:         str | None = Query(None),
    trace_id:        str | None = Query(None),
    from_time:       datetime | None = Query(None),
    to_time:         datetime | None = Query(None),
    include_ignored: bool = Query(False),
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        base = select(InsightRow).where(
            InsightRow.workspace_id == workspace.id,
            InsightRow.project_id == None,
        )
        if not include_ignored:
            base = base.where(InsightRow.status == "open")
        if severity:
            base = base.where(InsightRow.severity == severity)
        if rule_id:
            base = base.where(InsightRow.rule_id == rule_id)
        if trace_id:
            base = base.where(InsightRow.trace_id == trace_id)
        if from_time:
            base = base.where(InsightRow.created_at >= from_time)
        if to_time:
            base = base.where(InsightRow.created_at <= to_time)

        count_result = await session.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        rows_result = await session.execute(
            base.order_by(InsightRow.created_at.desc()).limit(limit).offset(offset)
        )
        rows = rows_result.scalars().all()

    return {
        "items": [_row_to_dict(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.patch("/{insight_id}")
async def patch_insight(
    insight_id: str,
    body: InsightPatch,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    if body.status is not None and body.status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_VALID_STATUSES)}")
    if body.severity is not None and body.severity not in _VALID_SEVERITIES:
        raise HTTPException(status_code=400, detail=f"severity must be one of {sorted(_VALID_SEVERITIES)}")

    async with get_session() as session:
        result = await session.execute(
            select(InsightRow).where(
                InsightRow.id == insight_id,
                InsightRow.workspace_id == workspace.id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Insight not found")
        if body.status is not None:
            row.status = body.status
        if body.severity is not None:
            row.severity = body.severity
        await session.flush()
        await session.refresh(row)

    return _row_to_dict(row)


@router.get("/{insight_id}")
async def get_insight(
    insight_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        result = await session.execute(
            select(InsightRow).where(
                InsightRow.id == str(insight_id),
                InsightRow.workspace_id == workspace.id,
            )
        )
        row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Insight not found")
    return _row_to_dict(row)


def _row_to_dict(r: InsightRow) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "trace_id": r.trace_id,
        "rule_id": r.rule_id,
        "severity": r.severity,
        "title": r.title,
        "detail": r.detail,
        "recommendation": r.recommendation,
        "affected_span_ids": r.affected_span_ids or [],
        "evidence": r.evidence,
        "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
