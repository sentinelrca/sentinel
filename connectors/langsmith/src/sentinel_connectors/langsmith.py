"""
LangSmith pull connector.

Fetches runs from the LangSmith REST API and maps them to NormalizedSpan objects.
Supports LangSmith Cloud and self-hosted deployments (LANGCHAIN_ENDPOINT).

LangSmith run_type → SpanKind:
  llm        → LLM_CALL
  tool       → TOOL_INVOKE
  retrieval  → RETRIEVAL
  agent      → AGENT_INVOKE
  chain      → CHAIN
  (other)    → GENERIC
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

import httpx

from sentinel_connectors.base import Connector
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.smith.langchain.com"
_PAGE_SIZE = 100

_KIND_MAP: dict[str, SpanKind] = {
    "llm":       SpanKind.LLM_CALL,
    "tool":      SpanKind.TOOL_INVOKE,
    "retrieval": SpanKind.RETRIEVAL,
    "agent":     SpanKind.AGENT_INVOKE,
    "chain":     SpanKind.CHAIN,
}


class LangSmithConnector(Connector):
    source_kind = "langsmith"

    def validate_config(self, config: dict) -> bool:
        try:
            resp = self._client(config).get("/api/v1/workspaces")
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("LangSmith config validation failed: %s", exc)
            return False

    def pull(
        self,
        config: dict,
        since: datetime,
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """
        Page through LangSmith runs newer than `since` using cursor-based pagination.
        Yields batches of NormalizedSpan objects.
        """
        client = self._client(config)
        project_name = config.get("project_name")
        cursor: str | None = None
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        while True:
            params: dict = {
                "limit": _PAGE_SIZE,
                "start_time": since_iso,
                "error": False,
            }
            if project_name:
                params["project_name"] = project_name
            if cursor:
                params["cursor"] = cursor

            try:
                resp = client.get("/api/v1/runs", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("LangSmith pull failed: %s", exc)
                return

            data = resp.json()
            runs = data if isinstance(data, list) else data.get("runs", [])
            if not runs:
                break

            batch = [
                self._map_run(run, workspace_id)
                for run in runs
                if run.get("trace_id")
            ]
            if batch:
                yield batch

            # LangSmith returns a cursor in response headers for next page
            cursor = resp.headers.get("x-cursor") or None
            if not cursor or len(runs) < _PAGE_SIZE:
                break

    # ------------------------------------------------------------------

    def _client(self, config: dict) -> httpx.Client:
        base_url = config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        api_key = config["api_key"]
        return httpx.Client(
            base_url=base_url,
            headers={"x-api-key": api_key},
            timeout=30.0,
        )

    def _map_run(self, run: dict, workspace_id: str) -> NormalizedSpan:
        run_type = (run.get("run_type") or "chain").lower()
        kind = _KIND_MAP.get(run_type, SpanKind.GENERIC)

        status = SpanStatus.ERROR if run.get("error") else SpanStatus.OK
        error_message = str(run.get("error") or "")

        start_time = _parse_ts(run.get("start_time"))
        end_time = _parse_ts(run.get("end_time")) or start_time

        # Token usage lives under extra.tokens or inputs/outputs metadata
        token_usage = run.get("token_usage") or {}
        input_tokens = int(
            token_usage.get("prompt_tokens") or
            token_usage.get("input_tokens") or 0
        )
        output_tokens = int(
            token_usage.get("completion_tokens") or
            token_usage.get("output_tokens") or 0
        )

        # Agent name from tags or extra metadata
        tags = run.get("tags") or []
        extra = run.get("extra") or {}
        metadata = extra.get("metadata") or {}
        agent_name = metadata.get("agent_name") or metadata.get("agentName") or ""

        # Model name from serialized LLM or extra
        serialized = run.get("serialized") or {}
        model = (
            run.get("extra", {}).get("invocation_params", {}).get("model_name") or
            serialized.get("model_name") or
            serialized.get("model") or
            ""
        )

        return NormalizedSpan(
            span_id=run["id"],
            trace_id=run["trace_id"],
            parent_span_id=run.get("parent_run_id"),
            name=run.get("name") or run_type,
            kind=kind,
            status=status,
            start_time=start_time,
            end_time=end_time,
            workspace_id=workspace_id,
            model=str(model),
            agent_name=agent_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_count=int(metadata.get("retry_count", 0)),
            error_message=error_message,
            attributes={
                "langsmith.run_type": run_type,
                "langsmith.session_name": run.get("session_name", ""),
                **(metadata or {}),
            },
        )


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)
