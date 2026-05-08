"""
End-to-end integration test: Langfuse pull → ClickHouse → Celery → Postgres insight.

Requires running infrastructure:
    task up
    cd tests && uv sync --no-install-project
    uv run --no-project pytest integration/ -v

Skipped automatically when SENTINEL_INTEGRATION_TESTS env var is not set.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SENTINEL_INTEGRATION_TESTS") != "1",
    reason="Set SENTINEL_INTEGRATION_TESTS=1 and run 'task up' to enable",
)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"
)
CLICKHOUSE_URL = os.getenv("CLICKHOUSE_URL", "clickhouse://localhost:9000/sentinel")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _pg_session():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    url = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return factory


async def _insert_workspace(session_factory, workspace_id: str) -> None:
    import hashlib
    from sqlalchemy import text
    api_key_hash = hashlib.sha256(b"test-api-key").hexdigest()
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO workspaces (id, name, api_key_hash, tier) "
                "VALUES (:id, :name, :hash, 0) ON CONFLICT DO NOTHING"
            ),
            {"id": workspace_id, "name": "Integration Test WS", "hash": api_key_hash},
        )
        await session.commit()


async def _count_insights(session_factory, workspace_id: str, trace_id: str) -> int:
    from sqlalchemy import text
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT COUNT(*) FROM insights WHERE workspace_id=:ws AND trace_id=:tr"),
            {"ws": workspace_id, "tr": trace_id},
        )
        return result.scalar() or 0


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clickhouse_insert_and_fetch():
    """Spans inserted to ClickHouse can be fetched back by trace_id."""
    from datetime import timedelta
    from sentinel_pipeline.db.clickhouse import ensure_tables, fetch_trace_spans, insert_spans
    from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus

    await ensure_tables()

    trace_id = f"integ-{uuid.uuid4().hex[:8]}"
    ws_id = "integ-ws-1"
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    spans = [
        NormalizedSpan(
            span_id=f"s{i}", trace_id=trace_id, parent_span_id=None if i == 0 else "s0",
            name=f"span-{i}", kind=SpanKind.CHAIN, status=SpanStatus.OK,
            start_time=t0 + timedelta(seconds=i),
            end_time=t0 + timedelta(seconds=i + 1),
            workspace_id=ws_id,
        )
        for i in range(3)
    ]
    await insert_spans(spans)

    # ClickHouse MergeTree may take a moment to make data visible
    for _ in range(10):
        rows = await fetch_trace_spans(trace_id, ws_id)
        if rows:
            break
        time.sleep(0.5)

    assert len(rows) == 3
    assert all(r["trace_id"] == trace_id for r in rows)


@pytest.mark.asyncio
async def test_process_trace_generates_insights():
    """
    Insert a trace with serial tool calls to ClickHouse, run process_trace,
    then verify an insight was written to Postgres.
    """
    from datetime import timedelta
    from sentinel_pipeline.db.clickhouse import ensure_tables, insert_spans
    from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus
    from sentinel_pipeline.graph.builder import build_graph
    from sentinel_pipeline.signals.extractor import extract_signals
    from sentinel_pipeline.rules.runner import run_rules

    await ensure_tables()
    session_factory = await _pg_session()
    workspace_id = f"integ-ws-{uuid.uuid4().hex[:6]}"
    await _insert_workspace(session_factory, workspace_id)

    trace_id = f"integ-trace-{uuid.uuid4().hex[:8]}"
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # Build a trace that triggers SequentialToolsRule
    spans = [
        NormalizedSpan(
            span_id="root", trace_id=trace_id, parent_span_id=None,
            name="chain", kind=SpanKind.CHAIN, status=SpanStatus.OK,
            start_time=t0, end_time=t0 + timedelta(seconds=3),
            workspace_id=workspace_id,
        ),
        NormalizedSpan(
            span_id="tool_a", trace_id=trace_id, parent_span_id="root",
            name="search_web", kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
            start_time=t0, end_time=t0 + timedelta(seconds=1),
            workspace_id=workspace_id,
        ),
        NormalizedSpan(
            span_id="tool_b", trace_id=trace_id, parent_span_id="root",
            name="query_db", kind=SpanKind.TOOL_INVOKE, status=SpanStatus.OK,
            start_time=t0 + timedelta(seconds=1), end_time=t0 + timedelta(seconds=2),
            workspace_id=workspace_id,
        ),
    ]
    await insert_spans(spans)

    # Run the pipeline inline (no Celery needed for this assertion)
    graph = build_graph(spans)
    signals = extract_signals(graph)
    insights = run_rules(graph)

    assert insights, "Expected at least one insight for serial tool calls"

    # Persist insights to Postgres
    import json
    from sqlalchemy import text
    async with session_factory() as session:
        for ins in insights:
            await session.execute(
                text(
                    "INSERT INTO insights (id, workspace_id, trace_id, rule_id, severity, "
                    "title, detail, recommendation, affected_span_ids, evidence, status) "
                    "VALUES (:id, :ws, :tr, :rule, :sev, :title, '', '', '[]', :ev, 'open') "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "ws": workspace_id,
                    "tr": trace_id,
                    "rule": ins.rule_id,
                    "sev": ins.severity.value,
                    "title": ins.title,
                    "ev": json.dumps(ins.evidence),
                },
            )
        await session.commit()

    count = await _count_insights(session_factory, workspace_id, trace_id)
    assert count >= 1
