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
            since:        Fetch only observations newer than this timestamp.
            workspace_id: Injected into every NormalizedSpan.workspace_id.
        """
        ...
