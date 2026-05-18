"""Projects router — manage and analyze collections of traces."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from celery import Celery
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from sentinel_pipeline.db.clickhouse import delete_project_spans
from sentinel_pipeline.db.postgres import (
    InsightRow,
    ProjectRow,
    WorkspaceRow,
    get_session,
)
from sentinel_pipeline.limits import get_import_limits

from ..middleware.auth import get_workspace

logger = logging.getLogger(__name__)

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
    status: Literal["pending", "importing", "ready", "error"]
    trace_count: int
    import_count: int
    created_at: datetime
    last_imported_at: datetime | None
    last_analyzed_at: datetime | None


def _project_to_out(row: ProjectRow) -> ProjectOut:
    return ProjectOut(
        id=row.id,
        workspace_id=row.workspace_id,
        name=row.name,
        filters=row.filters or {},
        status=row.status,
        trace_count=row.trace_count,
        import_count=row.import_count,
        created_at=row.created_at,
        last_imported_at=row.last_imported_at,
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


def _cleanup_project_spans(project_id: str, workspace_id: str) -> None:
    try:
        delete_project_spans(project_id, workspace_id)
    except Exception:
        logger.exception("Failed to clean up ClickHouse spans for project %s", project_id)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    background_tasks: BackgroundTasks,
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

    background_tasks.add_task(_cleanup_project_spans, project_id, workspace.id)


@router.post("/{project_id}/import")
async def import_project_endpoint(
    project_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, str]:
    limits = get_import_limits(workspace.tier)
    imports_per_week: int | None = limits.get("imports_per_week")

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

        if imports_per_week is not None:
            window_start = datetime.now(timezone.utc) - timedelta(days=7)
            count_result = await session.execute(
                select(func.count(ProjectRow.id)).where(
                    ProjectRow.workspace_id == workspace.id,
                    ProjectRow.last_imported_at >= window_start,
                )
            )
            imports_this_week = count_result.scalar_one()
            if imports_this_week >= imports_per_week:
                raise HTTPException(
                    status_code=402,
                    detail=f"Import quota exceeded ({imports_this_week}/{imports_per_week} per week)",
                )

    task = _celery.send_task(
        "import_project_traces",
        args=[project_id, workspace.id, workspace.tier],
    )
    return {"task_id": task.id}


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
