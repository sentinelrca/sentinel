"""
Integration tests for the Arize Phoenix connector against a real Phoenix instance.

Requires env vars (skip automatically if absent):
  PHOENIX_API_KEY      — Bearer token (omit for local OSS)
  PHOENIX_HOST         — Base URL, e.g. https://app.phoenix.arize.com/s/<space>
                         or http://localhost:6006 for local OSS
  PHOENIX_PROJECT_NAME — Project to use (default: "SentinelTest")

Run:
  cd tests
  PHOENIX_API_KEY=... PHOENIX_HOST=... uv run --no-project pytest integration/connectors/test_arize_integration.py -v
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

import pytest

from sentinel_connectors.arize import ArizePhoenixConnector

def _since() -> datetime:
    """5 minutes ago — spans ingested during this test run are always within window."""
    from datetime import timedelta
    return datetime.now(timezone.utc) - timedelta(minutes=5)
from sentinel_pipeline.models.span import SpanKind, SpanStatus

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_connector = ArizePhoenixConnector()


def _config() -> dict:
    host    = os.environ.get("PHOENIX_HOST", "")
    api_key = os.environ.get("PHOENIX_API_KEY", "")
    project = os.environ.get("PHOENIX_PROJECT_NAME", "SentinelTest")
    if not host:
        pytest.skip("PHOENIX_HOST not set — skipping Arize integration tests")
    cfg: dict = {"host": host, "project_name": project, "store_content": True}
    if api_key:
        cfg["api_key"] = api_key
    return cfg


def _ingest_spans(config: dict, spans: list[dict]) -> None:
    """POST spans directly via Phoenix REST API (no OTLP SDK needed)."""
    import httpx
    base    = config["host"].rstrip("/")
    project = config["project_name"]
    headers: dict = {"Content-Type": "application/json"}
    if api_key := config.get("api_key"):
        headers["Authorization"] = f"Bearer {api_key}"
    resp = httpx.post(
        f"{base}/v1/projects/{project}/spans",
        json={"data": spans},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    # Phoenix queues ingestion asynchronously; give it a moment to index
    time.sleep(2)


def _unique_trace() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex  # 32-char hex


def _span(
    trace_id: str,
    span_id: str,
    name: str,
    kind: str,
    *,
    parent_id: str | None = None,
    model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    input_val: str | None = None,
    output_val: str | None = None,
    status: str = "OK",
    status_message: str = "",
    offset_ms: int = 0,
) -> dict:
    t0    = datetime.now(timezone.utc)
    start = t0.replace(microsecond=offset_ms * 1000) if offset_ms < 1000 else t0
    end   = start.replace(second=min(start.second + 1, 59))
    attrs: dict = {"openinference.span.kind": kind}
    if model:
        attrs["llm.model_name"] = model
    if prompt_tokens is not None:
        attrs["llm.token_count.prompt"] = prompt_tokens
    if completion_tokens is not None:
        attrs["llm.token_count.completion"] = completion_tokens
    if input_val:
        attrs["input.value"] = input_val
    if output_val:
        attrs["output.value"] = output_val
    s: dict = {
        "name":           name,
        "context":        {"trace_id": trace_id, "span_id": span_id},
        "span_kind":      kind,
        "start_time":     start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "end_time":       end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "status_code":    status,
        "status_message": status_message,
        "attributes":     attrs,
    }
    if parent_id:
        s["parent_id"] = parent_id
    return s


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_validate_config():
    assert _connector.validate_config(_config()) is True


def test_pull_returns_ingested_llm_span():
    cfg      = _config()
    trace_id = _unique_trace()
    span_id  = uuid.uuid4().hex[:16]

    _ingest_spans(cfg, [_span(
        trace_id, span_id, "gpt-4o-mini-call", "LLM",
        model="gpt-4o-mini", prompt_tokens=150, completion_tokens=60,
        input_val="Summarise this document", output_val="The document covers...",
    )])

    since = _since()
    spans_by_id = {
        s.span_id: s
        for batch in _connector.pull(cfg, since, "ws-integration")
        for s in batch
    }

    assert span_id in spans_by_id, f"Ingested span {span_id} not found in pull results"
    s = spans_by_id[span_id]
    assert s.kind == SpanKind.LLM_CALL
    assert s.model == "gpt-4o-mini"
    assert s.input_tokens == 150
    assert s.output_tokens == 60
    assert s.trace_id == trace_id
    assert s.attributes["gen_ai.input"] == "Summarise this document"
    assert s.attributes["gen_ai.output"] == "The document covers..."


def test_pull_returns_retriever_and_tool_spans():
    cfg      = _config()
    trace_id = _unique_trace()
    root_id  = uuid.uuid4().hex[:16]
    ret_id   = uuid.uuid4().hex[:16]
    tool_id  = uuid.uuid4().hex[:16]

    _ingest_spans(cfg, [
        _span(trace_id, root_id,  "agent-root",    "AGENT"),
        _span(trace_id, ret_id,   "vector_search", "RETRIEVER", parent_id=root_id,
              input_val="refund policy"),
        _span(trace_id, tool_id,  "send_email",    "TOOL",      parent_id=root_id),
    ])

    since = _since()
    spans_by_id = {
        s.span_id: s
        for batch in _connector.pull(cfg, since, "ws-integration")
        for s in batch
    }

    assert ret_id  in spans_by_id
    assert tool_id in spans_by_id
    assert spans_by_id[ret_id].kind  == SpanKind.RETRIEVAL
    assert spans_by_id[tool_id].kind == SpanKind.TOOL_INVOKE
    assert spans_by_id[ret_id].parent_span_id == root_id


def test_pull_returns_error_span():
    cfg      = _config()
    trace_id = _unique_trace()
    span_id  = uuid.uuid4().hex[:16]

    _ingest_spans(cfg, [_span(
        trace_id, span_id, "failing-call", "LLM",
        status="ERROR", status_message="Rate limit exceeded",
    )])

    since = _since()
    spans_by_id = {
        s.span_id: s
        for batch in _connector.pull(cfg, since, "ws-integration")
        for s in batch
    }

    assert span_id in spans_by_id
    s = spans_by_id[span_id]
    assert s.status == SpanStatus.ERROR
    assert s.error_message == "Rate limit exceeded"


def test_pull_by_ids_returns_only_requested_trace():
    cfg       = _config()
    trace_a   = _unique_trace()
    trace_b   = _unique_trace()
    span_a_id = uuid.uuid4().hex[:16]
    span_b_id = uuid.uuid4().hex[:16]

    _ingest_spans(cfg, [
        _span(trace_a, span_a_id, "call-a", "LLM"),
        _span(trace_b, span_b_id, "call-b", "LLM"),
    ])

    batches = list(_connector.pull_by_ids(cfg, [trace_a], "ws-integration"))
    all_trace_ids = {s.trace_id for batch in batches for s in batch}
    assert trace_a in all_trace_ids
    assert trace_b not in all_trace_ids


def test_pull_by_window():
    cfg      = _config()
    trace_id = _unique_trace()
    span_id  = uuid.uuid4().hex[:16]

    _ingest_spans(cfg, [_span(trace_id, span_id, "windowed-call", "LLM")])

    since = _since()
    until = datetime(2026, 6, 3, 13, 0, 0, tzinfo=timezone.utc)
    spans_by_id = {
        s.span_id: s
        for batch in _connector.pull_by_window(cfg, since, until, "ws-integration")
        for s in batch
    }
    assert span_id in spans_by_id
