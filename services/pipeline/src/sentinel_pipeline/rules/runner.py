from __future__ import annotations

import logging

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.rules import REGISTRY

logger = logging.getLogger(__name__)


def run_rules(
    graph: FlowGraph,
    workspace_tier: Tier = Tier.FREE,
    rule_overrides: dict[str, dict] | None = None,
) -> list[Insight]:
    """
    Run all rules applicable to workspace_tier against the flow graph.

    rule_overrides maps rule_id → {action, severity} from workspace rule_configs:
      DISABLED          → rule is skipped
      OVERRIDE_SEVERITY → insight severity replaced with configured value

    Returns a flat list of insights. Rules that raise are logged and skipped.
    """
    overrides = rule_overrides or {}
    signals = extract_signals(graph)
    applicable = [r for r in REGISTRY if r.tier <= workspace_tier]

    all_insights: list[Insight] = []
    for rule in applicable:
        cfg = overrides.get(rule.id)
        if cfg and cfg.get("action") == "DISABLED":
            continue
        try:
            result = rule.evaluate(graph, signals)
            if result:
                if cfg and cfg.get("action") == "OVERRIDE_SEVERITY" and cfg.get("severity"):
                    result = [
                        i.model_copy(update={"severity": Severity(cfg["severity"])})
                        for i in result
                    ]
                all_insights.extend(result)
        except Exception:
            logger.exception("Rule %s raised unexpectedly on trace %s", rule.id, graph.trace_id)

    return all_insights
