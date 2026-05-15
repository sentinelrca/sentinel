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
        since_iso     = since.isoformat()

        while True:
            try:
                resp = client.get(
                    "/api/public/observations",
                    params={
                        "page":      page,
                        "limit":     _PAGE_SIZE,
                        "fromStartTime": since_iso,
                    },
                )
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("Langfuse pull failed on page %d: %s", page, exc)
                return

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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _client(self, config: dict) -> httpx.Client:
        base_url   = config.get("base_url", _DEFAULT_BASE_URL).rstrip("/")
        public_key = config["public_key"]
        secret_key = config["secret_key"]
        token      = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        return httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Basic {token}"},
            timeout=30.0,
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
