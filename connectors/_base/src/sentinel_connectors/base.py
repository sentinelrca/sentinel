from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Iterator

from sentinel_pipeline.models.span import NormalizedSpan


class Connector(ABC):
    """
    Abstract base for all source connectors.

    A connector knows how to pull NormalizedSpan batches from one observability
    source (Langfuse, LangSmith, Arize, etc.).

    The OTel push path (sources that emit OTLP directly) does NOT use this
    interface — it arrives via the ingestor's OTLP endpoint instead.

    Standard config keys (all connectors must honour these):
      store_content (bool, default False):
        When False (default), connectors must NOT store prompt/response content
        (inputs, outputs, messages) in span attributes. Only structural fields
        — token counts, latency, span kind, status — are retained.
        Set to True only when the workspace operator has explicitly opted in
        and accepts the data-retention implications.
    """

    source_kind: str  # e.g. "langfuse", "langsmith"

    @abstractmethod
    def validate_config(self, config: dict) -> bool:
        """
        Test that the provided credentials are valid by making a lightweight
        API call. Return True if valid, False if not. Must not raise.
        """
        ...

    @abstractmethod
    def pull(
        self,
        config: dict,
        since: datetime,
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """
        Yield batches of NormalizedSpan objects for traces observed after `since`.

        Yields lists (batches) rather than individual spans to allow callers to
        bulk-insert to ClickHouse efficiently. Batch size is implementation-defined.

        Args:
            config:       Source-specific credentials/config dict.
                          Must respect store_content (see class docstring).
            since:        Fetch only observations newer than this timestamp.
            workspace_id: Injected into every NormalizedSpan.workspace_id.
        """
        ...

    @abstractmethod
    def pull_by_window(
        self,
        config: dict,
        since: datetime,
        until: datetime,
        workspace_id: str,
        limit: int = 500,
    ) -> Iterator[list[NormalizedSpan]]:
        """
        Yield batches of NormalizedSpan objects within a closed time window.

        Used by offline project import to fetch a bounded, reproducible snapshot.
        Stops as soon as `limit` spans have been yielded (free-tier guard).

        Args:
            config:       Source-specific credentials/config dict.
            since:        Lower bound (inclusive) on observation start time.
            until:        Upper bound (inclusive) on observation start time.
            workspace_id: Injected into every NormalizedSpan.workspace_id.
            limit:        Maximum total spans to yield. Callers enforce this
                          as a trace-count proxy for free-tier quota.
        """
        ...

    @abstractmethod
    def pull_by_ids(
        self,
        config: dict,
        trace_ids: list[str],
        workspace_id: str,
    ) -> Iterator[list[NormalizedSpan]]:
        """
        Yield batches of NormalizedSpan objects for the given trace IDs.

        Used by offline project import when the user specifies exact traces.
        Makes one API call per trace ID (or per small batch, implementation-defined).

        Args:
            config:       Source-specific credentials/config dict.
            trace_ids:    Explicit list of trace IDs to fetch.
            workspace_id: Injected into every NormalizedSpan.workspace_id.
        """
        ...
