from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import fetch_trace_spans
from sentinel_pipeline.db.postgres import get_session, InsightRow
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
from sentinel_pipeline.models.insight import Tier
from sentinel_pipeline.rules.runner import run_rules

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

    # 3. Build flow graph + run rules
    graph    = build_graph(spans)
    insights = run_rules(graph, workspace_tier=tier)

    if not insights:
        return {"trace_id": trace_id, "insights": 0}

    # Deduplicate by rule_id — same rule may fire multiple times (e.g. agent_loop
    # fires once per cycling node). Merge affected_span_ids; keep highest severity.
    deduped: dict[str, object] = {}
    for ins in insights:
        if ins.rule_id not in deduped:
            deduped[ins.rule_id] = ins
        else:
            existing = deduped[ins.rule_id]
            merged_spans = list(dict.fromkeys(existing.affected_span_ids + ins.affected_span_ids))
            deduped[ins.rule_id] = existing.model_copy(update={"affected_span_ids": merged_spans})

    # 4. Persist insights (upsert by workspace_id + trace_id + rule_id)
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    async with get_session() as session:
        for insight in deduped.values():
            stmt = (
                pg_insert(InsightRow)
                .values(
                    id=insight.id,
                    workspace_id=insight.workspace_id,
                    trace_id=insight.trace_id,
                    rule_id=insight.rule_id,
                    severity=insight.severity.value,
                    title=insight.title,
                    detail=insight.detail,
                    recommendation=insight.recommendation,
                    affected_span_ids=insight.affected_span_ids,
                    evidence=insight.evidence,
                    status="open",
                )
                .on_conflict_do_update(
                    constraint="uq_insights_trace_rule",
                    set_=dict(
                        severity=insight.severity.value,
                        title=insight.title,
                        detail=insight.detail,
                        recommendation=insight.recommendation,
                        affected_span_ids=insight.affected_span_ids,
                        evidence=insight.evidence,
                    ),
                )
            )
            await session.execute(stmt)

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
