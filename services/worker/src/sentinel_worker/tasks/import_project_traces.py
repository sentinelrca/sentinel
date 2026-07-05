"""import_project_traces — pull traces from a connector into project_spans."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from sentinel_pipeline.db.clickhouse import delete_project_spans, insert_project_spans
from sentinel_pipeline.db.postgres import engine, ProjectRow, SourceRow, get_session
from sentinel_pipeline.crypto import decrypt_config
from sentinel_pipeline.limits import get_import_limits
from sentinel_pipeline.connectors import get_connector
from sentinel_worker.main import app

logger = logging.getLogger(__name__)


@app.task(bind=True, name="import_project_traces", max_retries=3)
def import_project_traces(
    self,
    project_id: str,
    workspace_id: str,
    workspace_tier: int = 0,
) -> dict:
    try:
        engine.sync_engine.dispose()
        return asyncio.run(_import_project_traces(project_id, workspace_id, workspace_tier))
    except Exception as exc:
        logger.exception("import_project_traces failed for project %s: %s", project_id, exc)
        raise self.retry(exc=exc, countdown=30 * (2**self.request.retries))


async def _import_project_traces(
    project_id: str,
    workspace_id: str,
    workspace_tier: int,
) -> dict:
    limits = get_import_limits(workspace_tier)

    async with get_session() as session:
        # Load project
        proj_result = await session.execute(
            select(ProjectRow).where(
                ProjectRow.id == project_id,
                ProjectRow.workspace_id == workspace_id,
            )
        )
        project = proj_result.scalar_one_or_none()
        if project is None:
            logger.warning("Project %s not found for workspace %s", project_id, workspace_id)
            return {"project_id": project_id, "traces": 0, "spans": 0}

        # Enforce rolling 7-day import quota (only when limit is set)
        imports_per_week = limits.get("imports_per_week")
        if imports_per_week is not None:
            window_start = datetime.now(timezone.utc) - timedelta(days=7)
            count_result = await session.execute(
                select(func.count(ProjectRow.id)).where(
                    ProjectRow.workspace_id == workspace_id,
                    ProjectRow.last_imported_at >= window_start,
                )
            )
            imports_this_week = count_result.scalar_one()
            if imports_this_week >= imports_per_week:
                logger.warning(
                    "Import quota exceeded for workspace %s (tier %d): "
                    "%d imports in last 7 days, limit is %d",
                    workspace_id,
                    workspace_tier,
                    imports_this_week,
                    imports_per_week,
                )
                # Set error status so the API can surface 429/402 to the user
                project.status = "error"
                return {
                    "project_id": project_id,
                    "error": "quota_exceeded",
                    "traces": 0,
                    "spans": 0,
                }

        # Load the workspace's source connector
        src_result = await session.execute(
            select(SourceRow).where(SourceRow.workspace_id == workspace_id)
        )
        source = src_result.scalars().first()
        if source is None:
            logger.error("No source configured for workspace %s", workspace_id)
            project.status = "error"
            return {"project_id": project_id, "error": "no_source", "traces": 0, "spans": 0}

        # Mark importing — commit before pulling so a crash leaves a recoverable state
        project.status = "importing"

    connector = get_connector(source.kind)
    if connector is None:
        async with get_session() as session:
            proj_result = await session.execute(
                select(ProjectRow).where(ProjectRow.id == project_id)
            )
            p = proj_result.scalar_one_or_none()
            if p:
                p.status = "error"
        logger.error("No connector for source kind '%s'", source.kind)
        return {"project_id": project_id, "error": "unknown_source_kind", "traces": 0, "spans": 0}

    config = decrypt_config(source.config_json)
    filters: dict = project.filters or {}
    trace_ids: list[str] | None = filters.get("trace_ids")
    date_from_str: str | None = filters.get("date_from")
    date_to_str: str | None = filters.get("date_to")
    traces_per_import: int | None = limits.get("traces_per_import")

    # Clear stale project_spans before re-import to prevent duplicate data accumulation.
    # project_spans uses plain MergeTree (no dedup), so we must delete explicitly.
    if project.import_count:
        await asyncio.to_thread(delete_project_spans, project_id, workspace_id)

    total_spans = 0
    trace_ids_seen: set[str] = set()

    try:
        if trace_ids:
            batches = connector.pull_by_ids(config, trace_ids, workspace_id)
        else:
            since = (
                datetime.fromisoformat(date_from_str)
                if date_from_str
                else datetime(2020, 1, 1, tzinfo=timezone.utc)
            )
            until = (
                datetime.fromisoformat(date_to_str) if date_to_str else datetime.now(timezone.utc)
            )
            limit = traces_per_import if traces_per_import is not None else 500
            batches = connector.pull_by_window(config, since, until, workspace_id, limit=limit)

        for batch in batches:
            await asyncio.to_thread(insert_project_spans, project_id, batch)
            total_spans += len(batch)
            for span in batch:
                trace_ids_seen.add(span.trace_id)

    except Exception as exc:
        logger.exception("Connector pull failed for project %s: %s", project_id, exc)
        async with get_session() as session:
            proj_result = await session.execute(
                select(ProjectRow).where(ProjectRow.id == project_id)
            )
            p = proj_result.scalar_one_or_none()
            if p:
                p.status = "error"
        return {"project_id": project_id, "error": str(exc), "traces": 0, "spans": 0}

    # Update project: ready, counts, timestamp
    async with get_session() as session:
        proj_result = await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
        p = proj_result.scalar_one_or_none()
        if p:
            p.status = "ready"
            p.trace_count = len(trace_ids_seen)
            p.import_count = (p.import_count or 0) + 1
            p.last_imported_at = datetime.now(timezone.utc)

    logger.info(
        "Imported project %s: %d spans across %d traces",
        project_id,
        total_spans,
        len(trace_ids_seen),
    )
    return {"project_id": project_id, "traces": len(trace_ids_seen), "spans": total_spans}
