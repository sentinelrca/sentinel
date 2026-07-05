from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sentinel_worker.main import app
from sentinel_pipeline.db.clickhouse import fetch_project_spans
from sentinel_pipeline.db.postgres import (
    engine,
    get_session,
    InsightRow,
    DetectorConfigRow,
    ProjectRow,
)
from sqlalchemy import select, delete
from sentinel_pipeline.graph.builder import build_graph
from sentinel_pipeline.models.span import NormalizedSpan
from sentinel_pipeline.models.insight import Insight, Tier
from sentinel_pipeline.detectors.runner import run_detectors
from sentinel_worker.tasks.process_trace import _row_to_span

logger = logging.getLogger(__name__)

_SEVERITY_RANK = {"info": 0, "warning": 1, "high": 2, "critical": 3}


def _dedupe_insights(insights: list[Insight]) -> list[Insight]:
    """Collapse insights to one per (trace_id, detector_id).

    The insights table enforces one row per (workspace, trace, detector,
    project), but a detector can legitimately emit several insights for one
    trace. Keep the highest-severity insight per key and merge the dropped
    insights' affected_span_ids into it so no span context is lost.
    """
    kept: dict[tuple[str, str], Insight] = {}
    for ins in insights:
        key = (ins.trace_id, ins.detector_id)
        winner = kept.get(key)
        if winner is None:
            kept[key] = ins
            continue
        # Merge affected spans (preserve order, de-duplicated)
        merged = list(dict.fromkeys([*winner.affected_span_ids, *ins.affected_span_ids]))
        if _SEVERITY_RANK.get(ins.severity.value, 0) > _SEVERITY_RANK.get(winner.severity.value, 0):
            ins.affected_span_ids = merged
            kept[key] = ins
        else:
            winner.affected_span_ids = merged
    return list(kept.values())


@app.task(name="analyze_project", bind=True, max_retries=3)
def analyze_project(self, project_id: str, workspace_id: str, workspace_tier: int = 0) -> dict:
    """
    Project analysis task: fetch spans from project_spans snapshot → build graphs
    → run rules → persist insights.

    Only runs when project.status == 'ready' (import must complete first).
    Sets status = 'analyzing' while running so the UI can show progress.
    """
    try:
        engine.sync_engine.dispose()
        return asyncio.run(_analyze_project(project_id, workspace_id, Tier(workspace_tier)))
    except Exception as exc:
        logger.exception("analyze_project failed for project %s: %s", project_id, exc)
        if self.request.retries >= self.max_retries:
            engine.sync_engine.dispose()
            asyncio.run(_mark_project_error(project_id, workspace_id))
            raise
        raise self.retry(exc=exc, countdown=2**self.request.retries)


async def _mark_project_error(project_id: str, workspace_id: str) -> None:
    async with get_session() as session:
        proj = (
            await session.execute(
                select(ProjectRow).where(
                    ProjectRow.id == project_id,
                    ProjectRow.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if proj is not None:
            proj.status = "error"


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

    if project.status not in ("ready", "analyzing"):
        logger.warning(
            "Project %s is not ready (status=%s) — import must complete before analysis",
            project_id,
            project.status,
        )
        return {"project_id": project_id, "insights": 0, "skipped": True}

    # 2. Mark as analyzing so the UI can show a spinner
    async with get_session() as session:
        proj = (
            await session.execute(
                select(ProjectRow).where(
                    ProjectRow.id == project_id,
                    ProjectRow.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if proj is not None:
            proj.status = "analyzing"

    # 3. Fetch spans from the project snapshot in ClickHouse
    raw_rows = await asyncio.to_thread(fetch_project_spans, project_id, workspace_id)

    if not raw_rows:
        logger.warning("No spans found in project snapshot %s", project_id)
        async with get_session() as session:
            proj = (
                await session.execute(
                    select(ProjectRow).where(
                        ProjectRow.id == project_id,
                        ProjectRow.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if proj is not None:
                proj.status = "ready"
        return {"project_id": project_id, "insights": 0}

    # 4. Deserialize to NormalizedSpan
    spans = [_row_to_span(row) for row in raw_rows]

    # 5. Load workspace detector overrides
    detector_overrides: dict[str, dict] = {}
    async with get_session() as session:
        cfg_result = await session.execute(
            select(DetectorConfigRow).where(DetectorConfigRow.workspace_id == workspace_id)
        )
        for cfg in cfg_result.scalars().all():
            detector_overrides[cfg.detector_id] = {"action": cfg.action, "severity": cfg.severity}

    # 6. Group spans by trace_id and run detectors per trace
    trace_groups: dict[str, list[NormalizedSpan]] = {}
    for span in spans:
        trace_groups.setdefault(span.trace_id, []).append(span)

    all_insights = []
    for trace_id, trace_spans in trace_groups.items():
        graph = build_graph(trace_spans)
        insights = run_detectors(graph, workspace_tier=tier, detector_overrides=detector_overrides)
        all_insights.extend(insights)

    # A detector may emit more than one insight for the same trace (e.g.
    # agent_loop finds two distinct loops). The insights table allows only one
    # row per (workspace, trace, detector, project), so collapse duplicates to
    # the highest-severity insight, folding the others' affected spans into it.
    all_insights = _dedupe_insights(all_insights)

    # 7. Persist: delete existing project insights, insert new ones,
    #    set status back to ready, update last_analyzed_at
    async with get_session() as session:
        await session.execute(
            delete(InsightRow).where(
                InsightRow.workspace_id == workspace_id,
                InsightRow.project_id == project_id,
            )
        )

        for insight in all_insights:
            session.add(
                InsightRow(
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
                    project_id=project_id,
                )
            )

        project_result = await session.execute(
            select(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.workspace_id == workspace_id,
            )
        )
        project_row = project_result.scalar_one_or_none()
        if project_row is not None:
            project_row.status = "ready"
            project_row.last_analyzed_at = datetime.now(timezone.utc)

    total_count = len(all_insights)
    logger.info("Analyzed project %s: %d insight(s)", project_id, total_count)
    return {"project_id": project_id, "insights": total_count}
