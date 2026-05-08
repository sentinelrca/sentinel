"""Unit tests for the Langfuse connector using respx to mock HTTP."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from sentinel_connectors.langfuse import LangfuseConnector
from sentinel_pipeline.models.span import SpanKind, SpanStatus

connector = LangfuseConnector()

_CONFIG = {
    "public_key": "pk-test",
    "secret_key": "sk-test",
    "base_url": "https://cloud.langfuse.com",
}

_WORKSPACE = "ws-test"
_SINCE = datetime(2026, 1, 1, tzinfo=timezone.utc)

_OBS_LLM = {
    "id": "obs-001",
    "traceId": "trace-abc",
    "parentObservationId": None,
    "type": "generation",
    "name": "gpt-4o call",
    "level": "DEFAULT",
    "startTime": "2026-01-01T00:00:00.000Z",
    "endTime": "2026-01-01T00:00:01.500Z",
    "model": "gpt-4o",
    "usage": {"input": 120, "output": 80},
    "statusMessage": None,
    "metadata": {},
    "projectId": "proj-1",
    "input": {},
}

_OBS_TOOL = {
    "id": "obs-002",
    "traceId": "trace-abc",
    "parentObservationId": "obs-001",
    "type": "tool",
    "name": "search_web",
    "level": "DEFAULT",
    "startTime": "2026-01-01T00:00:01.500Z",
    "endTime": "2026-01-01T00:00:02.500Z",
    "model": None,
    "usage": {},
    "statusMessage": None,
    "metadata": {"agent_name": "ResearchAgent"},
    "projectId": "proj-1",
    "input": {},
}

_OBS_ERROR = {
    "id": "obs-003",
    "traceId": "trace-xyz",
    "parentObservationId": None,
    "type": "span",
    "name": "bad_call",
    "level": "ERROR",
    "startTime": "2026-01-01T01:00:00.000Z",
    "endTime": "2026-01-01T01:00:00.100Z",
    "model": None,
    "usage": {},
    "statusMessage": "Timeout exceeded",
    "metadata": {},
    "projectId": "proj-1",
    "input": {},
}


def _page_response(observations: list[dict], total: int) -> dict:
    return {
        "data": observations,
        "meta": {"totalItems": total, "page": 1, "limit": 100},
    }


@respx.mock
def test_pull_maps_llm_observation():
    respx.get("https://cloud.langfuse.com/api/public/observations").mock(
        return_value=Response(200, json=_page_response([_OBS_LLM], total=1))
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert len(batches) == 1
    span = batches[0][0]
    assert span.span_id == "obs-001"
    assert span.trace_id == "trace-abc"
    assert span.kind == SpanKind.LLM_CALL
    assert span.model == "gpt-4o"
    assert span.input_tokens == 120
    assert span.output_tokens == 80
    assert span.workspace_id == _WORKSPACE


@respx.mock
def test_pull_maps_tool_observation():
    respx.get("https://cloud.langfuse.com/api/public/observations").mock(
        return_value=Response(200, json=_page_response([_OBS_TOOL], total=1))
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    span = batches[0][0]
    assert span.kind == SpanKind.TOOL_INVOKE
    assert span.name == "search_web"
    assert span.parent_span_id == "obs-001"
    assert span.agent_name == "ResearchAgent"


@respx.mock
def test_pull_maps_error_observation():
    respx.get("https://cloud.langfuse.com/api/public/observations").mock(
        return_value=Response(200, json=_page_response([_OBS_ERROR], total=1))
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    span = batches[0][0]
    assert span.status == SpanStatus.ERROR
    assert span.error_message == "Timeout exceeded"
    assert span.kind == SpanKind.CHAIN  # "span" type → CHAIN


@respx.mock
def test_pull_skips_observation_without_trace_id():
    orphan = {**_OBS_LLM, "traceId": None, "id": "orphan-1"}
    respx.get("https://cloud.langfuse.com/api/public/observations").mock(
        return_value=Response(200, json=_page_response([orphan], total=1))
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert batches == [], "Observations without traceId must be skipped"


@respx.mock
def test_pull_handles_empty_response():
    respx.get("https://cloud.langfuse.com/api/public/observations").mock(
        return_value=Response(200, json=_page_response([], total=0))
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert batches == []


@respx.mock
def test_pull_paginates_multiple_pages():
    """Connector fetches page 2 when page 1 is full (100 items), stops when page 2 is partial."""
    # Build a full first page of 100 identical observations with unique IDs
    full_page_obs = [{**_OBS_LLM, "id": f"obs-p1-{i}"} for i in range(100)]
    page1 = {"data": full_page_obs, "meta": {"totalItems": 101}}
    page2 = {"data": [{**_OBS_TOOL, "id": "obs-p2-0"}], "meta": {"totalItems": 101}}

    call_count = 0

    def _side_effect(request):
        nonlocal call_count
        call_count += 1
        return Response(200, json=page1 if call_count == 1 else page2)

    respx.get("https://cloud.langfuse.com/api/public/observations").mock(side_effect=_side_effect)

    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    all_spans = [s for batch in batches for s in batch]
    assert len(all_spans) == 101, f"Expected 101, got {len(all_spans)}"
    assert call_count == 2, "Should have made exactly 2 HTTP requests"


@respx.mock
def test_pull_stops_on_http_error():
    """HTTP error should not raise — connector logs and stops iteration."""
    respx.get("https://cloud.langfuse.com/api/public/observations").mock(
        return_value=Response(500, text="Internal Server Error")
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert batches == []


@respx.mock
def test_validate_config_returns_true_on_healthy():
    respx.get("https://cloud.langfuse.com/api/public/health").mock(
        return_value=Response(200, json={"status": "ok"})
    )
    assert connector.validate_config(_CONFIG) is True


@respx.mock
def test_validate_config_returns_false_on_failure():
    respx.get("https://cloud.langfuse.com/api/public/health").mock(
        return_value=Response(401)
    )
    assert connector.validate_config(_CONFIG) is False


def test_timestamps_parsed_correctly():
    """Timestamps with Z suffix and +00:00 suffix both parse to UTC."""
    obs_z   = {**_OBS_LLM, "startTime": "2026-03-15T12:00:00.000Z"}
    obs_utc = {**_OBS_LLM, "startTime": "2026-03-15T12:00:00.000+00:00", "id": "obs-004"}

    spans = [
        connector._map_observation(obs_z,   _WORKSPACE),
        connector._map_observation(obs_utc, _WORKSPACE),
    ]
    assert spans[0].start_time == spans[1].start_time
    assert spans[0].start_time.tzinfo is not None
