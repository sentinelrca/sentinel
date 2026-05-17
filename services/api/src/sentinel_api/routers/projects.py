"""Projects router — manage and analyze collections of traces."""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any

from celery import Celery
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select

from sentinel_pipeline.db.postgres import (
    InsightRow,
    ProjectRow,
    WorkspaceRow,
    get_session,
)

from ..middleware.auth import get_workspace

_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
_celery = Celery(broker=_REDIS_URL, backend=_REDIS_URL)

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    filters: dict = {}  # {date_from, date_to, trace_ids}


class ProjectOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    filters: dict
    created_at: datetime
    last_analyzed_at: datetime | None


def _project_to_out(row: ProjectRow) -> ProjectOut:
    return ProjectOut(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        filters=row.filters or {},
        created_at=row.created_at,
        last_analyzed_at=row.last_analyzed_at,
    )


@router.post("", status_code=201)
async def create_project(
    body: ProjectCreate,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> ProjectOut:
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name must not be empty")

    async with get_session() as session:
        row = ProjectRow(
            id=str(uuid.uuid4()),
            workspace_id=workspace.id,
            name=body.name,
            filters=body.filters,
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)

    return _project_to_out(row)


@router.get("")
async def list_projects(
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict:
    async with get_session() as session:
        result = await session.execute(
            select(ProjectRow).where(ProjectRow.workspace_id == workspace.id)
        )
        rows = result.scalars().all()

    items = [_project_to_out(r) for r in rows]
    return {"items": items, "total": len(items)}


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> ProjectOut:
    async with get_session() as session:
        result = await session.execute(
            select(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.workspace_id == workspace.id,
            )
        )
        row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return _project_to_out(row)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> None:
    async with get_session() as session:
        result = await session.execute(
            delete(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.workspace_id == workspace.id,
            )
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Project not found")


@router.post("/{project_id}/analyze")
async def analyze_project_endpoint(
    project_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, str]:
    async with get_session() as session:
        result = await session.execute(
            select(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.workspace_id == workspace.id,
            )
        )
        row = result.scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")

    task = _celery.send_task(
        "analyze_project",
        args=[project_id, workspace.id, workspace.tier],
    )
    return {"task_id": task.id}


@router.get("/{project_id}/insights")
async def get_project_insights(
    project_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        # Verify project belongs to this workspace
        proj_result = await session.execute(
            select(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.workspace_id == workspace.id,
            )
        )
        if proj_result.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Project not found")

        rows_result = await session.execute(
            select(InsightRow)
            .where(
                InsightRow.workspace_id == workspace.id,
                InsightRow.project_id == project_id,
                InsightRow.status == "open",
            )
            .order_by(InsightRow.created_at.desc())
        )
        rows = rows_result.scalars().all()

    items = [
        {
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
            "project_id": r.project_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    return {"items": items, "total": len(items)}
