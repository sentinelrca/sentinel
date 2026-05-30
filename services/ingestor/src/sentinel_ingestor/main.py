"""OTLP/HTTP ingestion endpoint. Accepts protobuf or JSON traces, queues processing."""
from __future__ import annotations

import asyncio
import hashlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, status
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from sentinel_pipeline.db.postgres import get_session, WorkspaceRow
from sqlalchemy import select

from .otel_mapper import map_otel_span

_CELERY_BROKER = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Import here to avoid circular deps at module load time
    from celery import Celery
    app.state.celery = Celery("sentinel_worker", broker=_CELERY_BROKER)
    yield


app = FastAPI(title="SentinelAI Ingestor", lifespan=lifespan)


async def _resolve_workspace(request: Request) -> WorkspaceRow:
    """Extract workspace from Authorization header (Bearer <api-key>)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")
    api_key = auth.removeprefix("Bearer ").strip()
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    async with get_session() as session:
        result = await session.execute(
            select(WorkspaceRow).where(WorkspaceRow.api_key_hash == key_hash)
        )
        ws = result.scalar_one_or_none()
    if ws is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return ws


@app.post("/v1/traces", status_code=status.HTTP_200_OK)
async def ingest_traces(request: Request) -> Response:
    """Accept OTLP ExportTraceServiceRequest (protobuf or JSON)."""
    content_type = request.headers.get("content-type", "")
    body = await request.body()

    ws = await _resolve_workspace(request)

    if "application/x-protobuf" in content_type:
        export_req = ExportTraceServiceRequest()
        export_req.ParseFromString(body)
    elif "application/json" in content_type:
        from google.protobuf import json_format
        export_req = json_format.Parse(body, ExportTraceServiceRequest())
    else:
        raise HTTPException(status_code=415, detail="Unsupported content type")

    spans = []
    for resource_spans in export_req.resource_spans:
        resource_attrs = {
            kv.key: kv.value.string_value
            for kv in resource_spans.resource.attributes
        }
        for scope_spans in resource_spans.scope_spans:
            for otel_span in scope_spans.spans:
                span = map_otel_span(otel_span, str(ws.id), resource_attrs)
                spans.append(span)

    if spans:
        from sentinel_pipeline.db.clickhouse import insert_spans
        await asyncio.to_thread(insert_spans, spans)

    trace_ids = {span.trace_id for span in spans}
    for trace_id in trace_ids:
        request.app.state.celery.send_task(
            "process_trace",
            kwargs={"workspace_id": str(ws.id), "trace_id": trace_id, "workspace_tier": ws.tier},
        )

    return Response(status_code=200)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
