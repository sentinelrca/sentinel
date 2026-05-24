"""
Detector registry.

Open source detectors are registered here. The commercial sentinel-engine package
appends additional detectors to DETECTOR_REGISTRY at import time when installed.
"""
from sentinel_pipeline.detectors.base import Detector
from sentinel_pipeline.detectors.agent_loop import AgentLoopDetector
from sentinel_pipeline.detectors.sequential_tools import SequentialToolsDetector
from sentinel_pipeline.detectors.missing_termination_condition import MissingTerminationConditionDetector
from sentinel_pipeline.detectors.token_cost_runaway import TokenCostRunawayDetector

DETECTOR_REGISTRY: list[Detector] = [
    AgentLoopDetector(),
    SequentialToolsDetector(),
    MissingTerminationConditionDetector(),
    TokenCostRunawayDetector(),
]

# Commercial engine hook: try to load additional detectors from sentinel_engine if installed.
try:
    from sentinel_engine.detectors import register  # type: ignore[import]
    register(DETECTOR_REGISTRY)
except ImportError:
    pass  # commercial engine not installed — open source mode

__all__ = ["Detector", "DETECTOR_REGISTRY"]
