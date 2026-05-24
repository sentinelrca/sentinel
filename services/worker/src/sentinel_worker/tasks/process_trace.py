from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import fetch_trace_spans
from sentinel_pipeline.db.postgres import get_session, InsightRow, DetectorConfigRow
from sqlalchemy import select
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.models.insight import Tier
from sentinel_pipeline.detectors.runner import run_detectors

logger = logging.getLogger(__name__)


@app.task(name="process_trace", bind=True, max_retries=3)
def process_trace(self, workspace_id: str, trace_id: str, workspace_tier: int = 0) -> dict:
    """
    Main pipeline task: fetch spans → build graph → run rules → persist insights.

    Args:
        workspace_id:   Workspace owning this trace.
        trace_id:       The trace to process.
        workspace_tier: Integer value of Tier enum (0=FREE, 1=STARTER, ...).
    """
    try:
        return asyncio.run(_process_trace(workspace_id, trace_id, Tier(workspace_tier)))
    except Exception as exc:
        logger.exception("process_trace failed for trace %s: %s", trace_id, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


async def _process_trace(workspace_id: str, trace_id: str, tier: Tier) -> dict:
    # 1. Fetch raw span rows from ClickHouse
    raw_rows = fetch_trace_spans(trace_id, workspace_id)
    if not raw_rows:
        logger.warning("No spans found for trace %s", trace_id)
        return {"trace_id": trace_id, "insights": 0}

    # 2. Deserialise to NormalizedSpan
    spans = [_row_to_span(row) for row in raw_rows]

    # 3. Load workspace detector overrides
    detector_overrides: dict[str, dict] = {}
    async with get_session() as session:
        cfg_result = await session.execute(
            select(DetectorConfigRow).where(DetectorConfigRow.workspace_id == workspace_id)
        )
        for cfg in cfg_result.scalars().all():
            detector_overrides[cfg.detector_id] = {"action": cfg.action, "severity": cfg.severity}

    # 4. Build flow graph + run detectors
    graph    = build_graph(spans)
    insights = run_detectors(graph, workspace_tier=tier, detector_overrides=detector_overrides)

    if not insights:
        return {"trace_id": trace_id, "insights": 0}

    # 5. Persist insights (upsert by workspace_id + trace_id + rule_id)
    async with get_session() as session:
        for insight in insights:
            row = InsightRow(
                id=insight.id,
                workspace_id=insight.workspace_id,
                trace_id=insight.trace_id,
                detector_id=insight.detector_id,
                severity=insight.severity.value,
                title=insight.title,
                detail=insight.detail,
                recommendation=insight.recommendation,
                affected_span_ids=insight.affected_span_ids,
                evidence=insight.evidence,
                status="open",
            )
            await session.merge(row)  # upsert by primary key

    logger.info("Processed trace %s: %d insight(s)", trace_id, len(insights))
    return {"trace_id": trace_id, "insights": len(insights)}


def _row_to_span(row: dict) -> NormalizedSpan:
    import json as _json
    from sentinel_pipeline.models.span import SpanKind, SpanStatus
    return NormalizedSpan(
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_span_id=row["parent_span_id"] or None,
        name=row["name"],
        kind=SpanKind(row["kind"]),
        status=SpanStatus(row["status"]),
        start_time=row["start_time"],
        end_time=row["end_time"],
        workspace_id=row["workspace_id"],
        model=row["model"] or None,
        agent_name=row["agent_name"] or None,
        input_tokens=row["input_tokens"] or None,
        output_tokens=row["output_tokens"] or None,
        retry_count=row["retry_count"],
        error_message=row["error_message"] or None,
        attributes=_json.loads(row["attributes_json"] or "{}"),
    )
