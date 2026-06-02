"""
Arize Phoenix pull connector.

Fetches spans from the Arize Phoenix REST API and maps them to
NormalizedSpan objects. Supports Phoenix OSS (self-hosted), Phoenix Cloud,
and Arize Enterprise.

OpenInference span.kind → SpanKind:
  LLM       → LLM_CALL
  CHAIN     → CHAIN
  RETRIEVER → RETRIEVAL
  TOOL      → TOOL_INVOKE
  AGENT     → AGENT_INVOKE
  EMBEDDING → GENERIC
  (other)   → GENERIC
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

import httpx

from sentinel_connectors.base import Connector
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://app.phoenix.arize.com"
_PAGE_SIZE        = 100

_KIND_MAP: dict[str, SpanKind] = {
    "llm":       SpanKind.LLM_CALL,
    "chain":     SpanKind.CHAIN,
    "retriever": SpanKind.RETRIEVAL,
    "tool":      SpanKind.TOOL_INVOKE,
    "agent":     SpanKind.AGENT_INVOKE,
    "embedding": SpanKind.GENERIC,
    "reranker":  SpanKind.GENERIC,
}


def _to_phoenix_ts(dt: datetime) -> str:
    """Format datetime as ISO 8601 with Z suffix, which Phoenix expects."""
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ArizePhoenixConnector(Connector):
    """
    Pull connector for Arize Phoenix (OSS, Cloud) and Arize Enterprise.

    Config keys:
      api_key      — Bearer token. Optional for local OSS (no auth).
      host         — Base URL. Defaults to https://app.phoenix.arize.com.
      project_name — Phoenix project to filter by. Optional.
      store_content — If True, store input.value / output.value as gen_ai.*
                      attributes on spans. Default False.
    """

    source_kind = "arize_phoenix"

    def validate_config(self, config: dict) -> bool:
        try:
            resp = self._client(config).get("/v1/spans", params={"page[size]": 1})
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Arize Phoenix config validation failed: %s", exc)
            return False

    def pull(
        self,
        config: dict,
        since: datetime,
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """Page through spans newer than `since` using cursor-based pagination."""
        client        = self._client(config)
        store_content = config.get("store_content", False)
        project_name  = config.get("project_name")
        cursor: str | None = None

        while True:
            params: dict = {
                "page[size]": _PAGE_SIZE,
                "start_time": _to_phoenix_ts(since),
            }
            if project_name:
                params["project_name"] = project_name
            if cursor:
                params["page[cursor]"] = cursor

            try:
                resp = client.get("/v1/spans", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("Arize Phoenix pull failed: %s", exc)
                raise

            body  = resp.json()
            spans = body.get("data", [])
            if not spans:
                break

            batch = [
                self._map_span(s, workspace_id, store_content)
                for s in spans
                if _trace_id(s)
            ]
            if batch:
                yield batch

            cursor = body.get("next_cursor") or None
            if not cursor or len(spans) < _PAGE_SIZE:
                break

    def pull_by_window(
        self,
        config: dict,
        since: datetime,
        until: datetime,
        workspace_id: str,
        limit: int = 500,
    ) -> Iterator[list[NormalizedSpan]]:
        """Fetch spans within [since, until], stopping after `limit` spans."""
        client        = self._client(config)
        store_content = config.get("store_content", False)
        project_name  = config.get("project_name")
        cursor: str | None = None
        total_yielded = 0

        while True:
            params: dict = {
                "page[size]": _PAGE_SIZE,
                "start_time": _to_phoenix_ts(since),
                "end_time":   _to_phoenix_ts(until),
            }
            if project_name:
                params["project_name"] = project_name
            if cursor:
                params["page[cursor]"] = cursor

            try:
                resp = client.get("/v1/spans", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("Arize Phoenix pull_by_window failed: %s", exc)
                raise

            body  = resp.json()
            spans = body.get("data", [])
            if not spans:
                break

            batch = [
                self._map_span(s, workspace_id, store_content)
                for s in spans
                if _trace_id(s)
            ]
            if batch:
                remaining = limit - total_yielded
                batch = batch[:remaining]
                yield batch
                total_yielded += len(batch)

            cursor = body.get("next_cursor") or None
            if total_yielded >= limit or not cursor or len(spans) < _PAGE_SIZE:
                break

    def pull_by_ids(
        self,
        config: dict,
        trace_ids: list[str],
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """Fetch all spans for the given trace IDs, one trace at a time."""
        client        = self._client(config)
        store_content = config.get("store_content", False)

        for trace_id in trace_ids:
            cursor: str | None = None
            trace_batch: list[NormalizedSpan] = []

            while True:
                params: dict = {
                    "trace_id":   trace_id,
                    "page[size]": _PAGE_SIZE,
                }
                if cursor:
                    params["page[cursor]"] = cursor

                try:
                    resp = client.get("/v1/spans", params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.error(
                        "Arize Phoenix pull_by_ids failed for trace %s: %s", trace_id, exc
                    )
                    raise

                body  = resp.json()
                spans = body.get("data", [])
                if not spans:
                    break

                trace_batch.extend(
                    self._map_span(s, workspace_id, store_content)
                    for s in spans
                    if _trace_id(s)
                )

                cursor = body.get("next_cursor") or None
                if not cursor or len(spans) < _PAGE_SIZE:
                    break

            if trace_batch:
                yield trace_batch

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _client(self, config: dict) -> httpx.Client:
        base_url = (config.get("host") or _DEFAULT_BASE_URL).rstrip("/")
        headers: dict = {}
        if api_key := config.get("api_key"):
            headers["Authorization"] = f"Bearer {api_key}"
        return httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    def _map_span(
        self,
        span: dict,
        workspace_id: str,
        store_content: bool = False,
    ) -> NormalizedSpan:
        ctx      = span.get("context") or {}
        span_id  = ctx.get("span_id") or span.get("id") or ""
        trace_id = ctx.get("trace_id") or ""
        attrs    = span.get("attributes") or {}

        # SpanKind: prefer OpenInference attribute; fall back to top-level field
        raw_kind = (
            attrs.get("openinference.span.kind")
            or span.get("spanKind")
            or span.get("span_kind")
            or ""
        ).lower()
        kind = _KIND_MAP.get(raw_kind, SpanKind.GENERIC)

        status_raw = (span.get("statusCode") or span.get("status_code") or "OK").upper()
        status     = SpanStatus.ERROR if status_raw == "ERROR" else SpanStatus.OK
        error_msg  = span.get("statusMessage") or span.get("status_message") or None

        start_time = (
            _parse_ts(span.get("startTime") or span.get("start_time"))
            or datetime.now(timezone.utc)
        )
        end_time = _parse_ts(span.get("endTime") or span.get("end_time")) or start_time

        input_tokens  = _int_or_none(attrs.get("llm.token_count.prompt"))
        output_tokens = _int_or_none(attrs.get("llm.token_count.completion"))
        model         = attrs.get("llm.model_name") or None

        metadata   = attrs.get("metadata") or {}
        agent_name = metadata.get("agent_name") or metadata.get("agentName") or None

        span_attrs: dict = {"arize.span_kind": raw_kind}
        if store_content:
            if input_val := attrs.get("input.value"):
                span_attrs["arize.input"]  = input_val
                span_attrs["gen_ai.input"] = input_val
            if output_val := attrs.get("output.value"):
                span_attrs["arize.output"]  = output_val
                span_attrs["gen_ai.output"] = output_val

        return NormalizedSpan(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=span.get("parentId") or span.get("parent_id") or None,
            name=span.get("name") or raw_kind or "span",
            kind=kind,
            status=status,
            start_time=start_time,
            end_time=end_time,
            workspace_id=workspace_id,
            model=model,
            agent_name=agent_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_count=0,
            error_message=error_msg,
            attributes=span_attrs,
        )


def _trace_id(span: dict) -> str | None:
    """Extract trace_id from a raw Phoenix span dict; return None if absent."""
    return (span.get("context") or {}).get("trace_id") or None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
