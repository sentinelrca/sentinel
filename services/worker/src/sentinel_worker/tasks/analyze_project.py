from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import fetch_spans_by_filter
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
    Project analysis task: fetch spans matching project filters → build graphs → run rules → persist insights.

    Args:
        project_id:     Project to analyze.
        workspace_id:   Workspace owning the project.
        workspace_tier: Integer value of Tier enum (0=FREE, 1=STARTER, ...).
    """
    try:
        return asyncio.run(_analyze_project(project_id, workspace_id, Tier(workspace_tier)))
    except Exception as exc:
        logger.exception("analyze_project failed for project %s: %s", project_id, exc)
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


async def _analyze_project(project_id: str, workspace_id: str, tier: Tier) -> dict:
    # 1. Load the project from Postgres
    async with get_session() as session:
        result = await session.execute(
            select(ProjectRow).where(ProjectRow.id == project_id)
        )
        project = result.scalar_one_or_none()

    if project is None:
        logger.warning("Project %s not found", project_id)
        return {"project_id": project_id, "insights": 0}

    # 2. Extract filters from project
    filters: dict = project.filters or {}
    date_from_str: str | None = filters.get("date_from")
    date_to_str: str | None = filters.get("date_to")
    trace_ids: list[str] | None = filters.get("trace_ids")

    date_from: datetime | None = datetime.fromisoformat(date_from_str) if date_from_str else None
    date_to: datetime | None = datetime.fromisoformat(date_to_str) if date_to_str else None

    # 3. Fetch spans from ClickHouse (synchronous, run in thread)
    raw_rows = await asyncio.to_thread(
        fetch_spans_by_filter, workspace_id, date_from, date_to, trace_ids
    )

    if not raw_rows:
        logger.warning("No spans found for project %s", project_id)
        return {"project_id": project_id, "insights": 0}

    # 4. Deserialize to NormalizedSpan
    spans = [_row_to_span(row) for row in raw_rows]

    # 5. Load workspace rule overrides
    rule_overrides: dict[str, dict] = {}
    async with get_session() as session:
        cfg_result = await session.execute(
            select(RuleConfigRow).where(RuleConfigRow.workspace_id == workspace_id)
        )
        for cfg in cfg_result.scalars().all():
            rule_overrides[cfg.rule_id] = {"action": cfg.action, "severity": cfg.severity}

    # 6. Group spans by trace_id
    trace_groups: dict[str, list[NormalizedSpan]] = {}
    for span in spans:
        trace_groups.setdefault(span.trace_id, []).append(span)

    # 7. Run rules per trace group and collect all insights
    all_insights = []
    for trace_id, trace_spans in trace_groups.items():
        graph = build_graph(trace_spans)
        insights = run_rules(graph, workspace_tier=tier, rule_overrides=rule_overrides)
        all_insights.extend(insights)

    # 8. Persist with idempotency: delete existing project insights, insert new ones,
    #    update last_analyzed_at — all in a single transaction
    async with get_session() as session:
        # Delete existing insights for this project
        await session.execute(
            delete(InsightRow).where(
                InsightRow.workspace_id == workspace_id,
                InsightRow.project_id == project_id,
            )
        )

        # Insert all new insights with project_id set
        for insight in all_insights:
            row = InsightRow(
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
            )
            session.add(row)

        # Update project timestamp
        project_result = await session.execute(
            select(ProjectRow).where(ProjectRow.id == project_id)
        )
        project_row = project_result.scalar_one_or_none()
        if project_row is not None:
            project_row.last_analyzed_at = datetime.now(timezone.utc)

    total_count = len(all_insights)
    logger.info("Analyzed project %s: %d insight(s)", project_id, total_count)
    return {"project_id": project_id, "insights": total_count}
