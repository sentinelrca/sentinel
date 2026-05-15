import { formatEvidence } from "@/lib/evidence";

describe("formatEvidence", () => {
  describe("null / missing evidence", () => {
    it("returns empty string for null evidence", () => {
      expect(formatEvidence("retry_storm", null)).toBe("");
    });

    it("returns empty string for undefined evidence", () => {
      expect(formatEvidence("retry_storm", undefined)).toBe("");
    });

    it("returns empty string for unknown rule", () => {
      expect(formatEvidence("unknown_rule", { foo: "bar" })).toBe("");
    });
  });

  describe("retry_storm", () => {
    it("formats with retry count and threshold", () => {
      expect(formatEvidence("retry_storm", { retry_count: 5, threshold: 3 })).toBe(
        "retried 5× — threshold is 3"
      );
    });

    it("formats with retry count only when threshold absent", () => {
      expect(formatEvidence("retry_storm", { retry_count: 4 })).toBe("retried 4×");
    });

    it("returns empty string when retry_count is missing", () => {
      expect(formatEvidence("retry_storm", { threshold: 3 })).toBe("");
    });
  });

  describe("latency_spike", () => {
    it("formats fraction and duration", () => {
      expect(formatEvidence("latency_spike", { fraction_pct: 72.5, duration_ms: 3400 })).toBe(
        "consumed 73% of trace duration (3400ms)"
      );
    });

    it("rounds fraction_pct to integer", () => {
      expect(formatEvidence("latency_spike", { fraction_pct: 50.1, duration_ms: 1000 })).toBe(
        "consumed 50% of trace duration (1000ms)"
      );
    });

    it("returns empty string when fields are missing", () => {
      expect(formatEvidence("latency_spike", { fraction_pct: 50 })).toBe("");
      expect(formatEvidence("latency_spike", { duration_ms: 1000 })).toBe("");
      expect(formatEvidence("latency_spike", {})).toBe("");
    });
  });

  describe("retrieval_without_grounding", () => {
    it("includes span name when present", () => {
      expect(
        formatEvidence("retrieval_without_grounding", { span_name: "search_docs" })
      ).toBe("'search_docs' returned 0 results, LLM still invoked");
    });

    it("uses generic message when span name absent", () => {
      expect(formatEvidence("retrieval_without_grounding", {})).toBe(
        "retrieval returned 0 results, LLM still invoked"
      );
    });
  });

  describe("context_cache_opportunity", () => {
    it("formats token growth and call count", () => {
      expect(
        formatEvidence("context_cache_opportunity", { total_growth: 1800, llm_call_count: 4 })
      ).toBe("tokens grew by 1800 across 4 LLM calls");
    });

    it("returns empty string when fields are missing", () => {
      expect(formatEvidence("context_cache_opportunity", { total_growth: 1800 })).toBe("");
      expect(formatEvidence("context_cache_opportunity", { llm_call_count: 4 })).toBe("");
    });
  });

  describe("missing_session_memory", () => {
    it("formats growth ratio and turn count", () => {
      expect(
        formatEvidence("missing_session_memory", { growth_ratio: 2.5, llm_call_count: 3 })
      ).toBe("tokens grew 2.5× across 3 turns, no memory tool found");
    });

    it("formats ratio to 1 decimal place", () => {
      expect(
        formatEvidence("missing_session_memory", { growth_ratio: 3.0, llm_call_count: 5 })
      ).toBe("tokens grew 3.0× across 5 turns, no memory tool found");
    });

    it("returns empty string when fields are missing", () => {
      expect(formatEvidence("missing_session_memory", { growth_ratio: 2 })).toBe("");
      expect(formatEvidence("missing_session_memory", { llm_call_count: 3 })).toBe("");
    });
  });

  describe("agent_loop", () => {
    it("formats invocation count and node name", () => {
      expect(
        formatEvidence("agent_loop", { invocations: 7, node_name: "ResearchAgent" })
      ).toBe("'ResearchAgent' executed 7 times — cycle detected");
    });

    it("returns empty string when invocations missing", () => {
      expect(formatEvidence("agent_loop", { node_name: "ResearchAgent" })).toBe("");
    });

    it("returns empty string when node_name missing", () => {
      expect(formatEvidence("agent_loop", { invocations: 7 })).toBe("");
    });
  });

  describe("sequential_tools", () => {
    it("formats tool count", () => {
      expect(formatEvidence("sequential_tools", { tool_count: 3 })).toBe(
        "3 tools ran sequentially under the same parent"
      );
    });

    it("returns empty string when tool_count missing", () => {
      expect(formatEvidence("sequential_tools", {})).toBe("");
    });
  });
});
