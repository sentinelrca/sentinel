from __future__ import annotations

from abc import ABC, abstractmethod

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.signals.extractor import Signals


class Rule(ABC):
    """
    Base class for all detection rules.

    Open source rules live in this package (tier=FREE).
    Commercial rules live in the sentinel-engine package and append
    themselves to REGISTRY at import time.
    """

    id:       str      # unique snake_case identifier, e.g. "agent_loop"
    name:     str      # human-readable, e.g. "Agent Loop"
    severity: Severity
    tier:     Tier     = Tier.FREE

    @abstractmethod
    def evaluate(self, graph: FlowGraph, signals: Signals) -> list[Insight] | None:
        """
        Analyse the flow graph and its pre-computed signals.

        Return a list of Insight objects if the rule fires, or None / [] if not.
        Must never raise — return None on unexpected input.
        """
        ...
