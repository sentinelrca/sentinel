type EvidenceMap = Record<string, unknown>;

export function formatEvidence(ruleId: string, evidence: EvidenceMap | null | undefined): string {
  if (!evidence) return "";

  switch (ruleId) {
    case "retry_storm": {
      const count = evidence.retry_count as number | undefined;
      return count !== undefined ? `retried ${count}× — threshold is 3` : "";
    }

    case "latency_spike": {
      const pct = evidence.fraction_pct as number | undefined;
      const ms = evidence.duration_ms as number | undefined;
      if (pct !== undefined && ms !== undefined) {
        return `consumed ${pct.toFixed(0)}% of trace duration (${ms}ms)`;
      }
      return "";
    }

    case "retrieval_without_grounding":
      return "retrieval returned 0 results, LLM still invoked";

    case "context_cache_opportunity": {
      const growth = evidence.total_growth as number | undefined;
      const calls = evidence.llm_call_count as number | undefined;
      if (growth !== undefined && calls !== undefined) {
        return `tokens grew by ${growth} across ${calls} LLM calls`;
      }
      return "";
    }

    case "missing_session_memory": {
      const ratio = evidence.growth_ratio as number | undefined;
      const calls = evidence.llm_call_count as number | undefined;
      if (ratio !== undefined && calls !== undefined) {
        return `tokens grew ${ratio.toFixed(1)}× across ${calls} turns, no memory tool found`;
      }
      return "";
    }

    case "agent_loop": {
      const loops = evidence.invocations as number | undefined;
      const node = evidence.node_name as string | undefined;
      if (loops !== undefined && node) {
        return `'${node}' executed ${loops} times — cycle detected`;
      }
      return "";
    }

    case "sequential_tools": {
      const count = evidence.tool_count as number | undefined;
      return count !== undefined
        ? `${count} tools ran sequentially under the same parent`
        : "";
    }

    default:
      return "";
  }
}
