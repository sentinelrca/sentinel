"""Traces router — trace-centric insight feed."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from sentinel_pipeline.db.clickhouse import count_distinct_traces, fetch_trace_stats_batch
from sentinel_pipeline.db.postgres import InsightRow, SourceRow, WorkspaceRow, get_session

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/traces", tags=["traces"])

_SEVERITY_ORDER = {"critical": 4, "high": 3, "warning": 2, "info": 1}


@router.get("")
async def list_traces(
    limit:  int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        count_result = await session.execute(
            select(func.count(InsightRow.trace_id.distinct())).where(
                InsightRow.workspace_id == workspace.id
            )
        )
        total = count_result.scalar_one()

        rows_result = await session.execute(
            select(
                InsightRow.trace_id,
                func.count().label("insight_count"),
                func.array_agg(InsightRow.rule_id).label("rule_ids"),
                func.max(InsightRow.created_at).label("latest_insight_at"),
                func.array_agg(InsightRow.severity).label("severities"),
            )
            .where(InsightRow.workspace_id == workspace.id)
            .group_by(InsightRow.trace_id)
            .order_by(func.max(InsightRow.created_at).desc())
            .limit(limit)
            .offset(offset)
        )
        groups = rows_result.all()

        severity_result = await session.execute(
            select(InsightRow.severity, func.count().label("cnt"))
            .where(InsightRow.workspace_id == workspace.id)
            .group_by(InsightRow.severity)
        )
        issues_by_severity = {row.severity: row.cnt for row in severity_result.all()}

        sync_result = await session.execute(
            select(func.max(SourceRow.last_synced_at)).where(
                SourceRow.workspace_id == workspace.id
            )
        )
        last_synced_at = sync_result.scalar_one()

    trace_ids = [g.trace_id for g in groups]
    total_traces_analyzed, stats = await asyncio.gather(
        asyncio.to_thread(count_distinct_traces, workspace.id),
        asyncio.to_thread(fetch_trace_stats_batch, trace_ids, workspace.id),
    )

    items = []
    for g in groups:
        severities = g.severities or []
        worst = max(severities, key=lambda s: _SEVERITY_ORDER.get(s, 0)) if severities else "info"
        span_stats = stats.get(g.trace_id, {"span_count": 0, "llm_calls": 0, "total_ms": 0})
        items.append({
            "trace_id": g.trace_id,
            "worst_severity": worst,
            "insight_count": g.insight_count,
            "rule_ids": list(dict.fromkeys(g.rule_ids)),  # dedup, preserve order
            "latest_insight_at": g.latest_insight_at.isoformat() if g.latest_insight_at else None,
            "span_count": span_stats["span_count"],
            "llm_calls": span_stats["llm_calls"],
            "total_ms": span_stats["total_ms"],
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "total_traces_analyzed": total_traces_analyzed,
        "issues_by_severity": issues_by_severity,
        "last_synced_at": last_synced_at.isoformat() if last_synced_at else None,
    }


@router.get("/{trace_id}/insights")
async def get_trace_insights(
    trace_id: str,
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    async with get_session() as session:
        rows_result = await session.execute(
            select(InsightRow)
            .where(
                InsightRow.workspace_id == workspace.id,
                InsightRow.trace_id == trace_id,
            )
            .order_by(InsightRow.created_at.desc())
        )
        rows = rows_result.scalars().all()

    return {
        "trace_id": trace_id,
        "items": [_insight_to_dict(r) for r in rows],
        "total": len(rows),
    }


def _insight_to_dict(r: InsightRow) -> dict[str, Any]:
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
