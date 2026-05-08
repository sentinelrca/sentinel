"""Unit tests for the LangSmith connector using respx to mock HTTP."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from sentinel_connectors.langsmith import LangSmithConnector
from sentinel_pipeline.models.span import SpanKind, SpanStatus

connector = LangSmithConnector()

_CONFIG = {
    "api_key": "lsv2_pt_test123",
    "base_url": "https://api.smith.langchain.com",
    "project_name": "my-project",
}

_WORKSPACE = "ws-test"
_SINCE = datetime(2026, 1, 1, tzinfo=timezone.utc)

_RUN_LLM = {
    "id": "run-001",
    "trace_id": "trace-abc",
    "parent_run_id": None,
    "run_type": "llm",
    "name": "ChatOpenAI",
    "start_time": "2026-01-01T00:00:00.000Z",
    "end_time": "2026-01-01T00:00:01.500Z",
    "error": None,
    "token_usage": {"prompt_tokens": 120, "completion_tokens": 80},
    "extra": {"invocation_params": {"model_name": "gpt-4o"}, "metadata": {}},
    "serialized": {},
    "tags": [],
    "session_name": "my-project",
}

_RUN_TOOL = {
    "id": "run-002",
    "trace_id": "trace-abc",
    "parent_run_id": "run-001",
    "run_type": "tool",
    "name": "search_web",
    "start_time": "2026-01-01T00:00:01.500Z",
    "end_time": "2026-01-01T00:00:02.500Z",
    "error": None,
    "token_usage": {},
    "extra": {"metadata": {"agent_name": "ResearchAgent"}},
    "serialized": {},
    "tags": [],
    "session_name": "my-project",
}

_RUN_AGENT = {
    "id": "run-003",
    "trace_id": "trace-xyz",
    "parent_run_id": None,
    "run_type": "agent",
    "name": "AgentExecutor",
    "start_time": "2026-01-01T01:00:00.000Z",
    "end_time": "2026-01-01T01:00:05.000Z",
    "error": None,
    "token_usage": {},
    "extra": {"metadata": {}},
    "serialized": {},
    "tags": [],
    "session_name": "my-project",
}

_RUN_ERROR = {
    "id": "run-004",
    "trace_id": "trace-err",
    "parent_run_id": None,
    "run_type": "chain",
    "name": "broken_chain",
    "start_time": "2026-01-01T02:00:00.000Z",
    "end_time": "2026-01-01T02:00:00.100Z",
    "error": "ValueError: context window exceeded",
    "token_usage": {},
    "extra": {"metadata": {}},
    "serialized": {},
    "tags": [],
    "session_name": "my-project",
}


@respx.mock
def test_pull_maps_llm_run():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[_RUN_LLM])
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert len(batches) == 1
    span = batches[0][0]
    assert span.span_id == "run-001"
    assert span.trace_id == "trace-abc"
    assert span.kind == SpanKind.LLM_CALL
    assert span.model == "gpt-4o"
    assert span.input_tokens == 120
    assert span.output_tokens == 80
    assert span.workspace_id == _WORKSPACE


@respx.mock
def test_pull_maps_tool_run():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[_RUN_TOOL])
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    span = batches[0][0]
    assert span.kind == SpanKind.TOOL_INVOKE
    assert span.name == "search_web"
    assert span.parent_span_id == "run-001"
    assert span.agent_name == "ResearchAgent"


@respx.mock
def test_pull_maps_agent_run():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[_RUN_AGENT])
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    span = batches[0][0]
    assert span.kind == SpanKind.AGENT_INVOKE
    assert span.status == SpanStatus.OK


@respx.mock
def test_pull_maps_error_run():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[_RUN_ERROR])
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    span = batches[0][0]
    assert span.status == SpanStatus.ERROR
    assert "ValueError" in span.error_message
    assert span.kind == SpanKind.CHAIN


@respx.mock
def test_pull_skips_run_without_trace_id():
    orphan = {**_RUN_LLM, "trace_id": None, "id": "orphan-1"}
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[orphan])
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert batches == []


@respx.mock
def test_pull_handles_empty_response():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[])
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert batches == []


@respx.mock
def test_pull_paginates_via_cursor():
    """When x-cursor header is present and page is full, fetches next page."""
    full_page = [{**_RUN_LLM, "id": f"run-p1-{i}", "trace_id": f"t-{i}"} for i in range(100)]
    page2 = [{**_RUN_TOOL, "id": "run-p2-0", "trace_id": "t-page2"}]

    call_count = 0

    def _side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json=full_page, headers={"x-cursor": "cursor-token-abc"})
        return Response(200, json=page2)

    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(side_effect=_side_effect)

    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    all_spans = [s for batch in batches for s in batch]
    assert len(all_spans) == 101
    assert call_count == 2


@respx.mock
def test_pull_stops_on_http_error():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(401, json={"detail": "Unauthorized"})
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert batches == []


@respx.mock
def test_validate_config_returns_true_on_success():
    respx.get("https://api.smith.langchain.com/api/v1/workspaces").mock(
        return_value=Response(200, json=[{"id": "ws-1"}])
    )
    assert connector.validate_config(_CONFIG) is True


@respx.mock
def test_validate_config_returns_false_on_unauthorized():
    respx.get("https://api.smith.langchain.com/api/v1/workspaces").mock(
        return_value=Response(403)
    )
    assert connector.validate_config(_CONFIG) is False


def test_timestamps_parsed_correctly():
    run_z = {**_RUN_LLM, "start_time": "2026-03-15T12:00:00.000Z"}
    run_utc = {**_RUN_LLM, "start_time": "2026-03-15T12:00:00.000+00:00", "id": "run-ts"}

    s1 = connector._map_run(run_z, _WORKSPACE)
    s2 = connector._map_run(run_utc, _WORKSPACE)
    assert s1.start_time == s2.start_time
    assert s1.start_time.tzinfo is not None
