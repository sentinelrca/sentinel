"""Unit tests for the LangSmith connector using respx to mock HTTP."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx
from httpx import Response

from sentinel_connectors.langsmith import LangSmithConnector, _parse_ts
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
def test_pull_raises_on_http_error():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(401, json={"detail": "Unauthorized"})
    )
    with pytest.raises(httpx.HTTPStatusError):
        list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))


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


# ---------------------------------------------------------------------------
# Regression tests for review fixes
# ---------------------------------------------------------------------------

def test_parse_ts_returns_none_for_missing_value():
    assert _parse_ts(None) is None
    assert _parse_ts("") is None


def test_parse_ts_returns_none_for_invalid_value():
    assert _parse_ts("not-a-date") is None


def test_missing_end_time_falls_back_to_start_time():
    """When end_time is absent, end_time must equal start_time — not datetime.now()."""
    run = {**_RUN_LLM, "end_time": None}
    span = connector._map_run(run, _WORKSPACE)
    assert span.end_time == span.start_time


@respx.mock
def test_error_runs_are_included_in_pull():
    """Error runs must NOT be filtered out — retry_storm and similar rules need them."""
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[_RUN_ERROR])
    )
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert len(batches) == 1, "Error run must appear in the batch"
    assert batches[0][0].span_id == "run-004"


def test_error_message_is_none_when_no_error():
    """error_message must be None (not empty string) when the run has no error."""
    run = {**_RUN_LLM, "error": None}
    span = connector._map_run(run, _WORKSPACE)
    assert span.error_message is None


def test_error_message_is_string_when_error_present():
    """error_message must be a non-empty string when the run has an error."""
    run = {**_RUN_ERROR}
    span = connector._map_run(run, _WORKSPACE)
    assert span.error_message is not None
    assert "ValueError" in span.error_message


def test_store_content_false_omits_inputs_and_outputs():
    """With store_content=False (default), inputs/outputs must NOT appear in attributes."""
    run = {
        **_RUN_LLM,
        "inputs":  {"prompt": "hello", "system": "you are a bot"},
        "outputs": {"text": "world"},
    }
    span = connector._map_run(run, _WORKSPACE, store_content=False)
    assert "langsmith.inputs" not in span.attributes
    assert "langsmith.outputs" not in span.attributes


def test_store_content_true_includes_inputs_and_outputs():
    """With store_content=True, inputs/outputs stored under namespaced keys."""
    run = {
        **_RUN_LLM,
        "inputs":  {"prompt": "hello"},
        "outputs": {"text": "world"},
    }
    span = connector._map_run(run, _WORKSPACE, store_content=True)
    assert span.attributes["langsmith.inputs"] == {"prompt": "hello"}
    assert span.attributes["langsmith.outputs"] == {"text": "world"}
    # structural attributes must still be present
    assert span.attributes["langsmith.run_type"] == "llm"


# ---------------------------------------------------------------------------
# pull_by_window
# ---------------------------------------------------------------------------

_UNTIL = datetime(2026, 1, 2, tzinfo=timezone.utc)


@respx.mock
def test_pull_by_window_returns_spans_in_range():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[_RUN_LLM])
    )
    batches = list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE))
    assert len(batches) == 1
    assert batches[0][0].span_id == "run-001"


@respx.mock
def test_pull_by_window_sends_correct_time_params():
    """start_time and end_time must be sent with the correct formatted values."""
    route = respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[])
    )
    list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE))
    assert route.called
    sent_params = dict(route.calls[0].request.url.params)
    since_iso = _SINCE.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    until_iso = _UNTIL.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    assert sent_params["start_time"] == since_iso
    assert sent_params["end_time"] == until_iso


@respx.mock
def test_pull_by_window_respects_limit():
    """Should stop after `limit` spans even if the page is full."""
    full_page = [{**_RUN_LLM, "id": f"run-{i}"} for i in range(100)]
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=full_page, headers={"x-cursor": "next"})
    )
    batches = list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE, limit=30))
    total = sum(len(b) for b in batches)
    assert total == 30


@respx.mock
def test_pull_by_window_empty_response():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[])
    )
    assert list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE)) == []


@respx.mock
def test_pull_by_window_raises_on_http_error():
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(500, text="error")
    )
    with pytest.raises(httpx.HTTPStatusError):
        list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE))


# ---------------------------------------------------------------------------
# pull_by_ids
# ---------------------------------------------------------------------------

@respx.mock
def test_pull_by_ids_fetches_per_trace():
    """One batch per trace ID that has runs."""
    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(
        return_value=Response(200, json=[_RUN_LLM])
    )
    batches = list(connector.pull_by_ids(_CONFIG, ["trace-abc", "trace-xyz"], _WORKSPACE))
    assert len(batches) == 2


@respx.mock
def test_pull_by_ids_skips_empty_trace():
    call_count = 0

    def _side(request):
        nonlocal call_count
        call_count += 1
        return Response(200, json=[_RUN_LLM] if call_count == 1 else [])

    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(side_effect=_side)
    batches = list(connector.pull_by_ids(_CONFIG, ["trace-abc", "trace-empty"], _WORKSPACE))
    assert len(batches) == 1


@respx.mock
def test_pull_by_ids_empty_trace_list():
    batches = list(connector.pull_by_ids(_CONFIG, [], _WORKSPACE))
    assert batches == []


@respx.mock
def test_pull_by_ids_http_error_skips_trace():
    """An HTTP error on one trace should not abort the whole iterator."""
    call_count = 0

    def _side(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(500, text="error")
        return Response(200, json=[_RUN_LLM])

    respx.get("https://api.smith.langchain.com/api/v1/runs").mock(side_effect=_side)
    batches = list(connector.pull_by_ids(_CONFIG, ["trace-bad", "trace-good"], _WORKSPACE))
    # trace-bad errors → skipped; trace-good succeeds → 1 batch with 1 span
    assert len(batches) == 1
    assert len(batches[0]) == 1
