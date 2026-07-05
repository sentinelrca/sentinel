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
    "llm": SpanKind.LLM_CALL,
    "tool": SpanKind.TOOL_INVOKE,
    "retrieval": SpanKind.RETRIEVAL,
    "agent": SpanKind.AGENT_INVOKE,
    "chain": SpanKind.CHAIN,
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
        store_content = config.get("store_content", False)
        project_name = config.get("project_name")
        cursor: str | None = None
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        while True:
            params: dict = {
                "limit": _PAGE_SIZE,
                "start_time": since_iso,
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
                raise

            data = resp.json()
            runs = data if isinstance(data, list) else data.get("runs", [])
            if not runs:
                break

            batch = [
                self._map_run(run, workspace_id, store_content)
                for run in runs
                if run.get("trace_id")
            ]
            if batch:
                yield batch

            # LangSmith returns a cursor in response headers for next page
            cursor = resp.headers.get("x-cursor") or None
            if not cursor or len(runs) < _PAGE_SIZE:
                break

    def pull_by_window(
        self,
        config: dict,
        since: datetime,
        until: datetime,
        workspace_id: str,
        limit: int = 500,
    ) -> Iterator[list[NormalizedSpan]]:
        """Fetch runs within [since, until], stopping after `limit` spans."""
        client = self._client(config)
        store_content = config.get("store_content", False)
        project_name = config.get("project_name")
        cursor: str | None = None
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        until_iso = until.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        total_yielded = 0

        while True:
            params: dict = {
                "limit": _PAGE_SIZE,
                "start_time": since_iso,
                "end_time": until_iso,
            }
            if project_name:
                params["project_name"] = project_name
            if cursor:
                params["cursor"] = cursor

            try:
                resp = client.get("/api/v1/runs", params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("LangSmith pull_by_window failed: %s", exc)
                raise

            data = resp.json()
            runs = data if isinstance(data, list) else data.get("runs", [])
            if not runs:
                break

            batch = [
                self._map_run(run, workspace_id, store_content)
                for run in runs
                if run.get("trace_id")
            ]
            if batch:
                remaining = limit - total_yielded
                batch = batch[:remaining]
                yield batch
                total_yielded += len(batch)

            cursor = resp.headers.get("x-cursor") or None
            if total_yielded >= limit or not cursor or len(runs) < _PAGE_SIZE:
                break

    def pull_by_ids(
        self,
        config: dict,
        trace_ids: list[str],
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """Fetch all runs for the given trace IDs, one trace at a time."""
        client = self._client(config)
        store_content = config.get("store_content", False)

        for trace_id in trace_ids:
            cursor: str | None = None
            trace_batch: list[NormalizedSpan] = []

            while True:
                params: dict = {"trace_id": trace_id, "limit": _PAGE_SIZE}
                if cursor:
                    params["cursor"] = cursor

                try:
                    resp = client.get("/api/v1/runs", params=params)
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.error("LangSmith pull_by_ids failed for trace %s: %s", trace_id, exc)
                    break

                data = resp.json()
                runs = data if isinstance(data, list) else data.get("runs", [])
                if not runs:
                    break

                trace_batch.extend(
                    self._map_run(run, workspace_id, store_content)
                    for run in runs
                    if run.get("trace_id")
                )
                cursor = resp.headers.get("x-cursor") or None
                if not cursor or len(runs) < _PAGE_SIZE:
                    break

            if trace_batch:
                yield trace_batch

    # ------------------------------------------------------------------

    def _client(self, config: dict) -> httpx.Client:
        base_url = config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        api_key = config["api_key"]
        return httpx.Client(
            base_url=base_url,
            headers={"x-api-key": api_key},
            timeout=30.0,
        )

    def _map_run(self, run: dict, workspace_id: str, store_content: bool = False) -> NormalizedSpan:
        run_type = (run.get("run_type") or "chain").lower()
        kind = _KIND_MAP.get(run_type, SpanKind.GENERIC)

        status = SpanStatus.ERROR if run.get("error") else SpanStatus.OK
        error_message = str(run["error"]) if run.get("error") else None

        start_time = _parse_ts(run.get("start_time")) or datetime.now(timezone.utc)
        end_time = _parse_ts(run.get("end_time")) or start_time

        # Token usage lives under extra.tokens or inputs/outputs metadata
        token_usage = run.get("token_usage") or {}
        input_tokens = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
        output_tokens = int(
            token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
        )

        extra = run.get("extra") or {}
        metadata = extra.get("metadata") or {}
        agent_name = metadata.get("agent_name") or metadata.get("agentName") or None

        # Model name from serialized LLM or extra
        serialized = run.get("serialized") or {}
        model = (
            run.get("extra", {}).get("invocation_params", {}).get("model_name")
            or serialized.get("model_name")
            or serialized.get("model")
            or ""
        )

        attributes: dict = {
            "langsmith.run_type": run_type,
            "langsmith.session_name": run.get("session_name", ""),
            **{f"langsmith.metadata.{k}": v for k, v in metadata.items()},
        }
        if store_content:
            if isinstance(run.get("inputs"), dict):
                attributes["langsmith.inputs"] = run["inputs"]
                attributes["gen_ai.input"] = run["inputs"]
            if isinstance(run.get("outputs"), dict):
                attributes["langsmith.outputs"] = run["outputs"]
                attributes["gen_ai.output"] = run["outputs"]

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
            model=str(model) or None,
            agent_name=agent_name or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_count=int(metadata.get("retry_count", 0)),
            error_message=error_message,
            attributes=attributes,
        )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
