"""
Detector registry.

Open source detectors are registered here. The commercial sentinel-engine package
appends additional detectors to DETECTOR_REGISTRY at import time when installed.
"""

from sentinel_pipeline.detectors.base import Detector
from sentinel_pipeline.detectors.unused_llm_output import UnusedLlmOutputDetector
from sentinel_pipeline.detectors.agent_loop import AgentLoopDetector
from sentinel_pipeline.detectors.sequential_tools import SequentialToolsDetector
from sentinel_pipeline.detectors.missing_termination_condition import (
    MissingTerminationConditionDetector,
)
from sentinel_pipeline.detectors.token_cost_runaway import TokenCostRunawayDetector
from sentinel_pipeline.detectors.retry_storm import RetryStormDetector
from sentinel_pipeline.detectors.latency_spike import LatencySpikeDetector
from sentinel_pipeline.detectors.context_cache_opportunity import ContextCacheOpportunityDetector
from sentinel_pipeline.detectors.retrieval_without_grounding import (
    RetrievalWithoutGroundingDetector,
)

DETECTOR_REGISTRY: list[Detector] = [
    AgentLoopDetector(),
    SequentialToolsDetector(),
    MissingTerminationConditionDetector(),
    TokenCostRunawayDetector(),
    RetryStormDetector(),
    LatencySpikeDetector(),
    ContextCacheOpportunityDetector(),
    RetrievalWithoutGroundingDetector(),
    UnusedLlmOutputDetector(),
]

# Commercial engine hook: try to load additional detectors from sentinel_engine if installed.
try:
    from sentinel_engine.detectors import register  # type: ignore[import]

    register(DETECTOR_REGISTRY)
except ImportError:
    pass  # commercial engine not installed — open source mode

__all__ = ["Detector", "DETECTOR_REGISTRY"]
