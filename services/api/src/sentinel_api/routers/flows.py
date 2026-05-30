"""Flows router — return flow graph JSON for a trace."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from sentinel_pipeline.db.clickhouse import fetch_project_trace_spans, fetch_trace_spans
from sentinel_pipeline.db.postgres import ProjectRow, WorkspaceRow, get_session
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sqlalchemy import select

from ..middleware.auth import get_workspace

router = APIRouter(prefix="/flows", tags=["flows"])
logger = logging.getLogger(__name__)


@router.get("/{trace_id}")
async def get_flow(
    trace_id: str,
    project_id: str | None = Query(None),
    workspace: WorkspaceRow = Depends(get_workspace),
) -> dict[str, Any]:
    if project_id:
        async with get_session() as session:
            proj = await session.execute(
                select(ProjectRow).where(
                    ProjectRow.id == project_id,
                    ProjectRow.workspace_id == workspace.id,
                )
            )
            if proj.scalar_one_or_none() is None:
                raise HTTPException(status_code=404, detail="Project not found")
        raw_rows = await asyncio.to_thread(
            fetch_project_trace_spans, project_id, trace_id, workspace.id
        )
    else:
        raw_rows = await asyncio.to_thread(fetch_trace_spans, trace_id, workspace.id)
    if not raw_rows:
        raise HTTPException(status_code=404, detail="Trace not found")

    spans = [_row_to_span(r) for r in raw_rows]
    graph = build_graph(spans)

    total_ms = (
        (max(s.end_time for s in spans) - min(s.start_time for s in spans)).total_seconds() * 1000
    )
    llm_calls = sum(1 for s in spans if s.kind == SpanKind.LLM_CALL)
    total_input = sum(s.input_tokens or 0 for s in spans)
    total_output = sum(s.output_tokens or 0 for s in spans)

    return {
        "trace_id": trace_id,
        "nodes": [
            {
                "id": s.span_id,
                "name": s.name,
                "kind": s.kind.value,
                "status": s.status.value,
                "start_time": s.start_time.isoformat(),
                "duration_ms": round(s.duration_ms, 1),
                "model": s.model,
                "agent_name": s.agent_name,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "retry_count": s.retry_count,
                "parent_id": s.parent_span_id,
                "error_message": s.error_message,
                "attributes": s.attributes,
            }
            for s in graph.nodes.values()
        ],
        "edges": [
            {
                "source": e.source_span_id,
                "target": e.target_span_id,
                "kind": e.kind.value,
            }
            for e in graph.edges
        ],
        "has_cycle": graph.has_cycle,
        "stats": {
            "total_ms": round(total_ms, 1),
            "span_count": len(spans),
            "llm_calls": llm_calls,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
        },
    }


def _row_to_span(row: dict) -> NormalizedSpan:
    try:
        kind = SpanKind(row["kind"])
    except ValueError:
        logger.warning("Unknown SpanKind %r for span %s — falling back to GENERIC", row["kind"], row["span_id"])
        kind = SpanKind.GENERIC
    try:
        status = SpanStatus(row["status"])
    except ValueError:
        logger.warning("Unknown SpanStatus %r for span %s — falling back to OK", row["status"], row["span_id"])
        status = SpanStatus.OK
    return NormalizedSpan(
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_span_id=row["parent_span_id"] or None,
        name=row["name"],
        kind=kind,
        status=status,
        start_time=row["start_time"],
        end_time=row["end_time"],
        workspace_id=row["workspace_id"],
        model=row["model"] or None,
        agent_name=row["agent_name"] or None,
        input_tokens=row["input_tokens"] or None,
        output_tokens=row["output_tokens"] or None,
        retry_count=row["retry_count"],
        error_message=row["error_message"] or None,
        attributes=json.loads(row["attributes_json"] or "{}"),
    )
