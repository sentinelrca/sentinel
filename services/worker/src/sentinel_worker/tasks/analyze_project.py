from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import fetch_project_spans
from sentinel_pipeline.db.postgres import (
    get_session,
    InsightRow,
    RuleConfigRow,
    ProjectRow,
)
from sqlalchemy import select, delete
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan
from sentinel_pipeline.models.insight import Tier
from sentinel_pipeline.rules.runner import run_rules
from sentinel_worker.tasks.process_trace import _row_to_span

logger = logging.getLogger(__name__)


@app.task(name="analyze_project", bind=True, max_retries=3)
def analyze_project(self, project_id: str, workspace_id: str, workspace_tier: int = 0) -> dict:
    """
    Project analysis task: fetch spans from project_spans snapshot → build graphs
    → run rules → persist insights.

    Only runs when project.status == 'ready' (import must complete first).
    """
    try:
        return asyncio.run(_analyze_project(project_id, workspace_id, Tier(workspace_tier)))
    except Exception as exc:
        logger.exception("analyze_project failed for project %s: %s", project_id, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


async def _analyze_project(project_id: str, workspace_id: str, tier: Tier) -> dict:
    # 1. Load the project and guard on status
    async with get_session() as session:
        result = await session.execute(
            select(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.workspace_id == workspace_id,
            )
        )
        project = result.scalar_one_or_none()

    if project is None:
        logger.warning("Project %s not found", project_id)
        return {"project_id": project_id, "insights": 0}

    if project.status != "ready":
        logger.warning(
            "Project %s is not ready (status=%s) — import must complete before analysis",
            project_id, project.status,
        )
        return {"project_id": project_id, "insights": 0, "skipped": True}

    # 2. Fetch spans from the project snapshot in ClickHouse
    raw_rows = await asyncio.to_thread(fetch_project_spans, project_id, workspace_id)

    if not raw_rows:
        logger.warning("No spans found in project snapshot %s", project_id)
        return {"project_id": project_id, "insights": 0}

    # 3. Deserialize to NormalizedSpan
    spans = [_row_to_span(row) for row in raw_rows]

    # 4. Load workspace rule overrides
    rule_overrides: dict[str, dict] = {}
    async with get_session() as session:
        cfg_result = await session.execute(
            select(RuleConfigRow).where(RuleConfigRow.workspace_id == workspace_id)
        )
        for cfg in cfg_result.scalars().all():
            rule_overrides[cfg.rule_id] = {"action": cfg.action, "severity": cfg.severity}

    # 5. Group spans by trace_id and run rules per trace
    trace_groups: dict[str, list[NormalizedSpan]] = {}
    for span in spans:
        trace_groups.setdefault(span.trace_id, []).append(span)

    all_insights = []
    for trace_id, trace_spans in trace_groups.items():
        graph = build_graph(trace_spans)
        insights = run_rules(graph, workspace_tier=tier, rule_overrides=rule_overrides)
        all_insights.extend(insights)

    # 6. Persist with idempotency: delete existing project insights, insert new ones,
    #    update last_analyzed_at — all in a single transaction
    async with get_session() as session:
        await session.execute(
            delete(InsightRow).where(
                InsightRow.workspace_id == workspace_id,
                InsightRow.project_id == project_id,
            )
        )

        for insight in all_insights:
            session.add(InsightRow(
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
                project_id=project_id,
            ))

        project_result = await session.execute(
            select(ProjectRow).where(ProjectRow.id == project_id)
        )
        project_row = project_result.scalar_one_or_none()
        if project_row is not None:
            project_row.last_analyzed_at = datetime.now(timezone.utc)

    total_count = len(all_insights)
    logger.info("Analyzed project %s: %d insight(s)", project_id, total_count)
    return {"project_id": project_id, "insights": total_count}
