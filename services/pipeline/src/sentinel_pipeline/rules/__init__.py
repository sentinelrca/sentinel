"""
Rule registry.

Open source rules are registered here. The commercial sentinel-engine package
appends additional rules to REGISTRY at import time when installed.
"""
from sentinel_pipeline.rules.base import Rule
from sentinel_pipeline.rules.agent_loop import AgentLoopRule
from sentinel_pipeline.rules.sequential_tools import SequentialToolsRule
from sentinel_pipeline.rules.retry_storm import RetryStormRule
from sentinel_pipeline.rules.latency_spike import LatencySpikeRule
from sentinel_pipeline.rules.retrieval_without_grounding import RetrievalWithoutGroundingRule
from sentinel_pipeline.rules.context_cache import ContextCacheOpportunityRule
from sentinel_pipeline.rules.missing_session_memory import MissingSessionMemoryRule

REGISTRY: list[Rule] = [
    AgentLoopRule(),
    SequentialToolsRule(),
    RetryStormRule(),
    LatencySpikeRule(),
    RetrievalWithoutGroundingRule(),
    ContextCacheOpportunityRule(),
    MissingSessionMemoryRule(),
]

# Commercial engine hook: try to load additional rules from sentinel_engine if installed.
try:
    from sentinel_engine.rules import register  # type: ignore[import]
    register(REGISTRY)
except ImportError:
    pass  # commercial engine not installed — open source mode

__all__ = ["Rule", "REGISTRY"]
