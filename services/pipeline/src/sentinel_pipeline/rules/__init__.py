"""
Rule registry.

Open source rules are registered here. The commercial sentinel-engine package
appends additional rules to REGISTRY at import time when installed.
"""
from sentinel_pipeline.rules.base import Rule
from sentinel_pipeline.rules.agent_loop import AgentLoopRule
from sentinel_pipeline.rules.sequential_tools import SequentialToolsRule

REGISTRY: list[Rule] = [
    AgentLoopRule(),
    SequentialToolsRule(),
]

# Commercial engine hook: try to load additional rules from sentinel_engine if installed.
try:
    from sentinel_engine.rules import register  # type: ignore[import]
    register(REGISTRY)
except ImportError:
    pass  # commercial engine not installed — open source mode

__all__ = ["Rule", "REGISTRY"]
