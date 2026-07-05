from __future__ import annotations

import logging

from sentinel_pipeline.models.graph import FlowGraph
from sentinel_pipeline.models.insight import Insight, Severity, Tier
from sentinel_pipeline.signals.extractor import extract_signals
from sentinel_pipeline.detectors import DETECTOR_REGISTRY

logger = logging.getLogger(__name__)


def run_detectors(
    graph: FlowGraph,
    workspace_tier: Tier = Tier.FREE,
    detector_overrides: dict[str, dict] | None = None,
) -> list[Insight]:
    """
    Run all detectors applicable to workspace_tier against the flow graph.

    detector_overrides maps detector_id → {action, severity} from workspace detector_configs:
      DISABLED          → detector is skipped
      OVERRIDE_SEVERITY → insight severity replaced with configured value

    Returns a flat list of insights. Detectors that raise are logged and skipped.
    """
    overrides = detector_overrides or {}
    signals = extract_signals(graph)
    applicable = [d for d in DETECTOR_REGISTRY if d.tier <= workspace_tier]

    all_insights: list[Insight] = []
    for detector in applicable:
        cfg = overrides.get(detector.id)
        if cfg and cfg.get("action") == "DISABLED":
            continue
        try:
            result = detector.evaluate(graph, signals)
            if result:
                if cfg and cfg.get("action") == "OVERRIDE_SEVERITY" and cfg.get("severity"):
                    result = [
                        i.model_copy(update={"severity": Severity(cfg["severity"])}) for i in result
                    ]
                all_insights.extend(result)
        except Exception:
            logger.exception(
                "Detector %s raised unexpectedly on trace %s", detector.id, graph.trace_id
            )

    return all_insights
