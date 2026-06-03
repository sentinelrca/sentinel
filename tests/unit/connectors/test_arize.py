"""Unit tests for the Arize Phoenix connector using respx to mock HTTP."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import respx
from httpx import Response

from sentinel_connectors.arize import ArizePhoenixConnector, _parse_ts
from sentinel_pipeline.models.span import SpanKind, SpanStatus

connector = ArizePhoenixConnector()

_PROJECT  = "SentinelTest"
_BASE_URL = "https://app.phoenix.arize.com"
_SPANS_URL = f"{_BASE_URL}/v1/projects/{_PROJECT}/spans"

_CONFIG = {
    "api_key":      "ak-test",
    "host":         _BASE_URL,
    "project_name": _PROJECT,
}

_CONFIG_LOCAL = {
    "host":         "http://localhost:6006",
    "project_name": _PROJECT,
    # no api_key — local OSS requires no auth
}

_WORKSPACE = "ws-test"
_SINCE     = datetime(2026, 1, 1, tzinfo=timezone.utc)
_UNTIL     = datetime(2026, 1, 2, tzinfo=timezone.utc)

# Real field names from Phoenix OpenAPI spec: all snake_case
_SPAN_LLM = {
    "id":             "sp-001",
    "context":        {"span_id": "sp-001", "trace_id": "trace-abc"},
    "parent_id":      None,
    "name":           "gpt-4o inference",
    "span_kind":      "LLM",
    "status_code":    "OK",
    "status_message": "",
    "start_time":     "2026-01-01T00:00:00.000Z",
    "end_time":       "2026-01-01T00:00:01.500Z",
    "attributes": {
        "openinference.span.kind":    "LLM",
        "llm.model_name":             "gpt-4o",
        "llm.token_count.prompt":     120,
        "llm.token_count.completion": 80,
        "input.value":                "What is the capital of France?",
        "output.value":               "Paris.",
    },
    "events": [],
}

_SPAN_RETRIEVER = {
    "id":             "sp-002",
    "context":        {"span_id": "sp-002", "trace_id": "trace-abc"},
    "parent_id":      "sp-001",
    "name":           "vector_search",
    "span_kind":      "RETRIEVER",
    "status_code":    "OK",
    "status_message": "",
    "start_time":     "2026-01-01T00:00:00.500Z",
    "end_time":       "2026-01-01T00:00:00.800Z",
    "attributes":     {"openinference.span.kind": "RETRIEVER"},
    "events":         [],
}

_SPAN_TOOL = {
    "id":             "sp-003",
    "context":        {"span_id": "sp-003", "trace_id": "trace-abc"},
    "parent_id":      "sp-001",
    "name":           "send_email",
    "span_kind":      "TOOL",
    "status_code":    "OK",
    "status_message": "",
    "start_time":     "2026-01-01T00:00:01.000Z",
    "end_time":       "2026-01-01T00:00:01.200Z",
    "attributes":     {"openinference.span.kind": "TOOL"},
    "events":         [],
}

_SPAN_ERROR = {
    "id":             "sp-004",
    "context":        {"span_id": "sp-004", "trace_id": "trace-xyz"},
    "parent_id":      None,
    "name":           "bad_call",
    "span_kind":      "LLM",
    "status_code":    "ERROR",
    "status_message": "Rate limit exceeded",
    "start_time":     "2026-01-01T01:00:00.000Z",
    "end_time":       "2026-01-01T01:00:00.100Z",
    "attributes":     {},
    "events":         [],
}


def _page(data: list[dict], next_cursor: str | None = None) -> dict:
    body: dict = {"data": data}
    if next_cursor:
        body["next_cursor"] = next_cursor
    return body


# ---------------------------------------------------------------------------
# pull — span mapping
# ---------------------------------------------------------------------------

@respx.mock
def test_pull_maps_llm_span():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([_SPAN_LLM])))
    batches = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))
    assert len(batches) == 1
    span = batches[0][0]
    assert span.span_id == "sp-001"
    assert span.trace_id == "trace-abc"
    assert span.kind == SpanKind.LLM_CALL
    assert span.model == "gpt-4o"
    assert span.input_tokens == 120
    assert span.output_tokens == 80
    assert span.workspace_id == _WORKSPACE


@respx.mock
def test_pull_maps_retriever_span():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([_SPAN_RETRIEVER])))
    span = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))[0][0]
    assert span.kind == SpanKind.RETRIEVAL
    assert span.parent_span_id == "sp-001"


@respx.mock
def test_pull_maps_tool_span():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([_SPAN_TOOL])))
    span = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))[0][0]
    assert span.kind == SpanKind.TOOL_INVOKE
    assert span.name == "send_email"


@respx.mock
def test_pull_maps_error_span():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([_SPAN_ERROR])))
    span = list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))[0][0]
    assert span.status == SpanStatus.ERROR
    assert span.error_message == "Rate limit exceeded"


# ---------------------------------------------------------------------------
# pull — structural behavior
# ---------------------------------------------------------------------------

@respx.mock
def test_pull_skips_span_without_trace_id():
    orphan = {**_SPAN_LLM, "context": {"span_id": "orphan", "trace_id": None}}
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([orphan])))
    assert list(connector.pull(_CONFIG, _SINCE, _WORKSPACE)) == []


@respx.mock
def test_pull_handles_empty_response():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([])))
    assert list(connector.pull(_CONFIG, _SINCE, _WORKSPACE)) == []


@respx.mock
def test_pull_paginates_via_cursor():
    """Two pages: first returns next_cursor, second returns no cursor — both fetched."""
    full_page = [
        {**_SPAN_LLM, "id": f"sp-p1-{i}", "context": {"span_id": f"sp-p1-{i}", "trace_id": "t1"}}
        for i in range(100)
    ]
    page2 = [{**_SPAN_RETRIEVER, "id": "sp-p2-0", "context": {"span_id": "sp-p2-0", "trace_id": "t1"}}]

    call_count = 0

    def _side(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json=_page(full_page, next_cursor="cursor-abc"))
        return Response(200, json=_page(page2))

    respx.get(_SPANS_URL).mock(side_effect=_side)

    all_spans = [s for batch in connector.pull(_CONFIG, _SINCE, _WORKSPACE) for s in batch]
    assert len(all_spans) == 101
    assert call_count == 2


@respx.mock
def test_pull_stops_when_no_next_cursor():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([_SPAN_LLM])))
    assert len(list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))) == 1


@respx.mock
def test_pull_raises_on_http_error():
    import httpx
    respx.get(_SPANS_URL).mock(return_value=Response(500, text="Internal Server Error"))
    with pytest.raises(httpx.HTTPStatusError):
        list(connector.pull(_CONFIG, _SINCE, _WORKSPACE))


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

@respx.mock
def test_validate_config_true():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([])))
    assert connector.validate_config(_CONFIG) is True


@respx.mock
def test_validate_config_false():
    respx.get(_SPANS_URL).mock(return_value=Response(401))
    assert connector.validate_config(_CONFIG) is False


@respx.mock
def test_no_auth_header_when_no_api_key():
    """Local OSS mode: no api_key in config → no Authorization header sent."""
    local_url = f"http://localhost:6006/v1/projects/{_PROJECT}/spans"
    route = respx.get(local_url).mock(return_value=Response(200, json=_page([])))
    list(connector.pull(_CONFIG_LOCAL, _SINCE, _WORKSPACE))
    assert route.called
    assert "authorization" not in route.calls[0].request.headers


# ---------------------------------------------------------------------------
# pull_by_window
# ---------------------------------------------------------------------------

@respx.mock
def test_pull_by_window_returns_spans_in_range():
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([_SPAN_LLM])))
    batches = list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE))
    assert len(batches) == 1
    assert batches[0][0].span_id == "sp-001"


@respx.mock
def test_pull_by_window_sends_time_params():
    """Both start_time and end_time must be present in the request."""
    route = respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([])))
    list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE))
    assert route.called
    params = dict(route.calls[0].request.url.params)
    assert "start_time" in params
    assert "end_time" in params


@respx.mock
def test_pull_by_window_respects_limit():
    full_page = [
        {**_SPAN_LLM, "id": f"sp-{i}", "context": {"span_id": f"sp-{i}", "trace_id": "t1"}}
        for i in range(100)
    ]
    respx.get(_SPANS_URL).mock(
        return_value=Response(200, json=_page(full_page, next_cursor="cursor-x"))
    )
    batches = list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE, limit=50))
    assert sum(len(b) for b in batches) == 50


@respx.mock
def test_pull_by_window_raises_on_http_error():
    import httpx
    respx.get(_SPANS_URL).mock(return_value=Response(500, text="error"))
    with pytest.raises(httpx.HTTPStatusError):
        list(connector.pull_by_window(_CONFIG, _SINCE, _UNTIL, _WORKSPACE))


# ---------------------------------------------------------------------------
# pull_by_ids
# ---------------------------------------------------------------------------

@respx.mock
def test_pull_by_ids_fetches_per_trace():
    """One batch yielded per trace ID that has spans."""
    respx.get(_SPANS_URL).mock(return_value=Response(200, json=_page([_SPAN_LLM])))
    batches = list(connector.pull_by_ids(_CONFIG, ["trace-abc", "trace-xyz"], _WORKSPACE))
    assert len(batches) == 2


@respx.mock
def test_pull_by_ids_skips_empty_trace():
    call_count = 0

    def _side(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json=_page([_SPAN_LLM]))
        return Response(200, json=_page([]))

    respx.get(_SPANS_URL).mock(side_effect=_side)
    batches = list(connector.pull_by_ids(_CONFIG, ["trace-abc", "trace-empty"], _WORKSPACE))
    assert len(batches) == 1
    assert batches[0][0].trace_id == "trace-abc"


@respx.mock
def test_pull_by_ids_empty_list():
    assert list(connector.pull_by_ids(_CONFIG, [], _WORKSPACE)) == []


@respx.mock
def test_pull_by_ids_raises_on_http_error():
    import httpx
    respx.get(_SPANS_URL).mock(return_value=Response(500, text="error"))
    with pytest.raises(httpx.HTTPStatusError):
        list(connector.pull_by_ids(_CONFIG, ["trace-bad"], _WORKSPACE))


# ---------------------------------------------------------------------------
# store_content
# ---------------------------------------------------------------------------

def test_store_content_false_omits_gen_ai_keys():
    span = connector._map_span(_SPAN_LLM, _WORKSPACE, store_content=False)
    assert "gen_ai.input" not in span.attributes
    assert "gen_ai.output" not in span.attributes


def test_store_content_true_adds_gen_ai_keys():
    span = connector._map_span(_SPAN_LLM, _WORKSPACE, store_content=True)
    assert span.attributes["gen_ai.input"] == "What is the capital of France?"
    assert span.attributes["gen_ai.output"] == "Paris."


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------

def test_parse_ts_returns_none_for_missing():
    assert _parse_ts(None) is None
    assert _parse_ts("") is None


def test_parse_ts_handles_z_and_utc_suffix():
    assert _parse_ts("2026-03-15T12:00:00.000Z") == _parse_ts("2026-03-15T12:00:00.000+00:00")


def test_missing_end_time_falls_back_to_start_time():
    span_no_end = {**_SPAN_LLM, "end_time": None}
    span = connector._map_span(span_no_end, _WORKSPACE)
    assert span.end_time == span.start_time
