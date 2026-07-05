"""Maps OpenTelemetry spans to NormalizedSpan using OTel GenAI semantic conventions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from opentelemetry.proto.trace.v1.trace_pb2 import Span as OtelSpan

from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus

_NANOS_PER_MS = 1_000_000
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# gen_ai.operation.name → SpanKind
_OPERATION_TO_KIND: dict[str, SpanKind] = {
    "chat": SpanKind.LLM_CALL,
    "completion": SpanKind.LLM_CALL,
    "embeddings": SpanKind.LLM_CALL,
    "tool": SpanKind.TOOL_INVOKE,
    "retrieval": SpanKind.RETRIEVAL,
    "agent": SpanKind.AGENT_INVOKE,
    "chain": SpanKind.CHAIN,
}

_OTEL_STATUS_TO_SPAN_STATUS: dict[int, SpanStatus] = {
    0: SpanStatus.OK,  # STATUS_CODE_UNSET
    1: SpanStatus.OK,  # STATUS_CODE_OK
    2: SpanStatus.ERROR,  # STATUS_CODE_ERROR
}


def _ns_to_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def _hex(b: bytes) -> str:
    return b.hex() if b else ""


def map_otel_span(
    span: OtelSpan, workspace_id: str, resource_attrs: dict[str, Any]
) -> NormalizedSpan:
    """Convert a single OTel span proto to NormalizedSpan."""
    attrs: dict[str, Any] = {kv.key: _extract_value(kv.value) for kv in span.attributes}
    merged = {**resource_attrs, **attrs}

    operation = merged.get("gen_ai.operation.name", "")
    kind = _OPERATION_TO_KIND.get(str(operation).lower(), SpanKind.CHAIN)

    status = _OTEL_STATUS_TO_SPAN_STATUS.get(span.status.code, SpanStatus.OK)
    error_message = span.status.message or ""
    if status == SpanStatus.ERROR and not error_message:
        error_message = merged.get("exception.message", "")

    parent_id = _hex(span.parent_span_id) or None

    return NormalizedSpan(
        trace_id=_hex(span.trace_id),
        span_id=_hex(span.span_id),
        parent_span_id=parent_id,
        workspace_id=workspace_id,
        name=span.name,
        kind=kind,
        status=status,
        start_time=_ns_to_dt(span.start_time_unix_nano),
        end_time=_ns_to_dt(span.end_time_unix_nano),
        model=str(merged.get("gen_ai.request.model", "")),
        agent_name=str(merged.get("gen_ai.agent.name", "")),
        input_tokens=int(merged.get("gen_ai.usage.input_tokens", 0) or 0),
        output_tokens=int(merged.get("gen_ai.usage.output_tokens", 0) or 0),
        retry_count=int(merged.get("gen_ai.retry.count", 0) or 0),
        error_message=str(error_message),
        attributes={k: v for k, v in merged.items()},
    )


def _extract_value(av: Any) -> Any:
    """Extract a Python value from an OTel AnyValue proto."""
    kind = av.WhichOneof("value")
    if kind == "string_value":
        return av.string_value
    if kind == "int_value":
        return av.int_value
    if kind == "double_value":
        return av.double_value
    if kind == "bool_value":
        return av.bool_value
    if kind == "array_value":
        return [_extract_value(v) for v in av.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _extract_value(kv.value) for kv in av.kvlist_value.values}
    return None
