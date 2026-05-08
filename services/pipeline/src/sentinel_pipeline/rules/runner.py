from __future__ import annotations

import logging

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Tier
from sentinel_pipeline.signals.extractor import Signals, extract_signals
from sentinel_pipeline.rules import REGISTRY

logger = logging.getLogger(__name__)


def run_rules(graph: FlowGraph, workspace_tier: Tier = Tier.FREE) -> list[Insight]:
    """
    Run all rules applicable to workspace_tier against the flow graph.

    Returns a flat list of insights. Rules that raise are logged and skipped
    rather than propagating — a broken rule must never take down the pipeline.
    """
    signals = extract_signals(graph)
    applicable = [r for r in REGISTRY if r.tier <= workspace_tier]

    all_insights: list[Insight] = []
    for rule in applicable:
        try:
            result = rule.evaluate(graph, signals)
            if result:
                all_insights.extend(result)
        except Exception:
            logger.exception("Rule %s raised unexpectedly on trace %s", rule.id, graph.trace_id)

    return all_insights
