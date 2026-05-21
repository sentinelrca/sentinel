"""
Langfuse pull connector.

Fetches observations from the Langfuse REST API and maps them to
NormalizedSpan objects. Supports both Langfuse Cloud and self-hosted.

Langfuse observation types → SpanKind:
  LLM / generation  → LLM_CALL
  tool              → TOOL_INVOKE
  retrieval         → RETRIEVAL
  span              → CHAIN
  (anything else)   → GENERIC
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Iterator

import httpx

from sentinel_connectors.base import Connector
from sentinel_pipeline.models.span import NormalizedSpan, SpanKind, SpanStatus

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://cloud.langfuse.com"
_PAGE_SIZE        = 100


def _to_langfuse_ts(dt: datetime) -> str:
    """Format datetime as ISO 8601 with Z suffix — Langfuse rejects +00:00 encoding."""
    utc = dt.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


_KIND_MAP: dict[str, SpanKind] = {
    "llm":        SpanKind.LLM_CALL,
    "generation": SpanKind.LLM_CALL,
    "tool":       SpanKind.TOOL_INVOKE,
    "retrieval":  SpanKind.RETRIEVAL,
    "span":       SpanKind.CHAIN,   # Langfuse v2 type name
    "chain":      SpanKind.CHAIN,   # Langfuse v4 type name
}


class LangfuseConnector(Connector):
    source_kind = "langfuse"

    def validate_config(self, config: dict) -> bool:
        try:
            client = self._client(config)
            resp = client.get("/api/public/health")
            return resp.status_code == 200
        except Exception as exc:
            logger.warning("Langfuse config validation failed: %s", exc)
            return False

    def pull(
        self,
        config: dict,
        since: datetime,
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """
        Page through Langfuse observations newer than `since` and yield
        batches of NormalizedSpan objects.
        """
        client        = self._client(config)
        store_content = config.get("store_content", False)
        page          = 1
        since_iso     = _to_langfuse_ts(since)

        while True:
            try:
                resp = client.get(
                    f"/api/public/observations?page={page}&limit={_PAGE_SIZE}"
                    f"&fromStartTime={since_iso}",
                )
                if resp.status_code == 422:
                    logger.warning(
                        "Langfuse observations API 422 on page %d — stopping: %s",
                        page, resp.text[:200],
                    )
                    break
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("Langfuse pull HTTP %d on page %d: %s", exc.response.status_code, page, exc)
                raise
            except httpx.HTTPError as exc:
                logger.error("Langfuse pull failed on page %d: %s", page, exc)
                raise

            data = resp.json()
            observations = data.get("data", [])
            if not observations:
                break

            batch = [
                self._map_observation(obs, workspace_id, store_content)
                for obs in observations
                if obs.get("traceId")  # skip orphaned observations
            ]
            if batch:
                yield batch

            # If we got fewer items than a full page, we've reached the last page
            if len(observations) < _PAGE_SIZE:
                break
            page += 1

    def pull_by_window(
        self,
        config: dict,
        since: datetime,
        until: datetime,
        workspace_id: str,
        limit: int = 500,
    ) -> Iterator[list[NormalizedSpan]]:
        """Fetch observations within [since, until], stopping after `limit` spans."""
        client        = self._client(config)
        store_content = config.get("store_content", False)
        page          = 1
        total_yielded = 0

        while True:
            try:
                resp = client.get(
                    f"/api/public/observations?page={page}&limit={_PAGE_SIZE}"
                    f"&fromStartTime={_to_langfuse_ts(since)}"
                    f"&toStartTime={_to_langfuse_ts(until)}",
                )
                if resp.status_code == 422:
                    logger.warning(
                        "Langfuse observations API 422 on page %d — "
                        "stopping pagination (partial results preserved): %s",
                        page, resp.text[:200],
                    )
                    break
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("Langfuse pull_by_window HTTP %d on page %d: %s", exc.response.status_code, page, exc)
                raise
            except httpx.HTTPError as exc:
                logger.error("Langfuse pull_by_window failed on page %d: %s", page, exc)
                raise

            observations = resp.json().get("data", [])
            if not observations:
                break

            batch = [
                self._map_observation(obs, workspace_id, store_content)
                for obs in observations
                if obs.get("traceId")
            ]
            if batch:
                remaining = limit - total_yielded
                batch = batch[:remaining]
                yield batch
                total_yielded += len(batch)

            if total_yielded >= limit or len(observations) < _PAGE_SIZE:
                break
            page += 1  # only reached when page was full and limit not yet hit

    def pull_by_ids(
        self,
        config: dict,
        trace_ids: list[str],
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """Fetch all observations for the given trace IDs, one trace at a time."""
        client        = self._client(config)
        store_content = config.get("store_content", False)

        for trace_id in trace_ids:
            page = 1
            trace_batch: list[NormalizedSpan] = []

            while True:
                try:
                    resp = client.get(
                        "/api/public/observations",
                        params={
                            "traceId": trace_id,
                            "page":    page,
                            "limit":   _PAGE_SIZE,
                        },
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.error("Langfuse pull_by_ids HTTP %d for trace %s: %s", exc.response.status_code, trace_id, exc)
                    raise
                except httpx.HTTPError as exc:
                    logger.error("Langfuse pull_by_ids failed for trace %s: %s", trace_id, exc)
                    raise

                observations = resp.json().get("data", [])
                if not observations:
                    break

                trace_batch.extend(
                    self._map_observation(obs, workspace_id, store_content)
                    for obs in observations
                    if obs.get("traceId")
                )
                if len(observations) < _PAGE_SIZE:
                    break
                page += 1

            if trace_batch:
                yield trace_batch

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _client(self, config: dict) -> httpx.Client:
        base_url   = (config.get("host") or config.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        public_key = config["public_key"]
        secret_key = config["secret_key"]
        token      = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        return httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Basic {token}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    def _map_observation(self, obs: dict, workspace_id: str, store_content: bool = False) -> NormalizedSpan:
        obs_type = (obs.get("type") or "span").lower()
        kind     = _KIND_MAP.get(obs_type, SpanKind.GENERIC)

        status = SpanStatus.OK
        if obs.get("level") == "ERROR":
            status = SpanStatus.ERROR

        # Langfuse timestamps are ISO 8601 strings
        start_time = _parse_ts(obs.get("startTime")) or datetime.now(timezone.utc)
        end_time   = _parse_ts(obs.get("endTime")) or start_time

        usage         = obs.get("usage") or {}
        input_tokens  = usage.get("input")  or usage.get("promptTokens")
        output_tokens = usage.get("output") or usage.get("completionTokens")

        # Agent name: Langfuse doesn't have a native field; check metadata
        metadata   = obs.get("metadata") or {}
        agent_name = metadata.get("agent_name") or metadata.get("agentName")

        attributes: dict = {
            "langfuse.type":    obs_type,
            "langfuse.project": obs.get("projectId", ""),
        }
        if store_content and isinstance(obs.get("input"), dict):
            attributes["langfuse.input"] = obs["input"]

        return NormalizedSpan(
            span_id=obs["id"],
            trace_id=obs["traceId"],
            parent_span_id=obs.get("parentObservationId"),
            name=obs.get("name") or obs_type,
            kind=kind,
            status=status,
            start_time=start_time,
            end_time=end_time,
            workspace_id=workspace_id,
            model=obs.get("model"),
            agent_name=agent_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_count=int(metadata.get("retry_count", 0)),
            error_message=obs.get("statusMessage"),
            attributes=attributes,
        )


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    # Handle both Z and +00:00 suffixes
    value = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
