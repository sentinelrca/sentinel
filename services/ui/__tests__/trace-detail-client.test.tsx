import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import TraceDetailClient from "@/app/traces/[trace_id]/trace-detail-client";
import type { FlowGraph, Insight } from "@/lib/types";

// Mock ReactFlow — it requires ResizeObserver + canvas APIs not available in jsdom
jest.mock("@xyflow/react", () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="react-flow">{children}</div>
  ),
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
}));
// Suppress the CSS import from flow-graph
jest.mock("@xyflow/react/dist/style.css", () => ({}), { virtual: true });

function makeFlow(overrides: Partial<FlowGraph> = {}): FlowGraph {
  return {
    trace_id: "trace-abc",
    nodes: [
      {
        id: "s1", name: "llm_call", kind: "llm_call", status: "ok",
        duration_ms: 800, model: "gpt-4o", agent_name: null,
        input_tokens: 100, output_tokens: 50, retry_count: 0,
        parent_id: null, error_message: null, attributes: {},
      },
      {
        id: "s2", name: "tool_exec", kind: "tool_invoke", status: "ok",
        duration_ms: 200, model: null, agent_name: null,
        input_tokens: 0, output_tokens: 0, retry_count: 0,
        parent_id: "s1", error_message: null, attributes: {},
      },
    ],
    edges: [{ source: "s1", target: "s2", kind: "parent_child" }],
    has_cycle: false,
    stats: { total_ms: 1000, span_count: 2, llm_calls: 1, total_input_tokens: 100, total_output_tokens: 50 },
    ...overrides,
  };
}

function makeInsight(id: string, ruleId: string, spanId: string): Insight {
  return {
    id,
    trace_id: "trace-abc",
    rule_id: ruleId,
    severity: "high",
    title: `${ruleId} detected`,
    detail: "detail",
    recommendation: "rec",
    affected_span_ids: [spanId],
    evidence: { retry_count: 4, threshold: 3 },
    status: "open",
    created_at: "2026-01-01T00:00:00Z",
  };
}

describe("TraceDetailClient", () => {
  it("renders the graph tab by default", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });

  it("switches to timeline view when Timeline tab is clicked", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    fireEvent.click(screen.getByRole("button", { name: /timeline/i }));
    // Timeline renders span name rows
    expect(screen.getByText("llm_call")).toBeInTheDocument();
    expect(screen.queryByTestId("react-flow")).not.toBeInTheDocument();
  });

  it("switches back to graph when Graph tab is clicked", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    fireEvent.click(screen.getByRole("button", { name: /timeline/i }));
    fireEvent.click(screen.getByRole("button", { name: /graph/i }));
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
  });

  it("lists all insights in the left panel", () => {
    const insights = [
      makeInsight("i1", "retry_storm", "s1"),
      makeInsight("i2", "latency_spike", "s2"),
    ];
    render(<TraceDetailClient flow={makeFlow()} insights={insights} traceId="trace-abc" />);
    expect(screen.getByText("retry_storm")).toBeInTheDocument();
    expect(screen.getByText("latency_spike")).toBeInTheDocument();
  });

  it("shows issue count in the left panel header", () => {
    const insights = [makeInsight("i1", "retry_storm", "s1"), makeInsight("i2", "agent_loop", "s1")];
    render(<TraceDetailClient flow={makeFlow()} insights={insights} traceId="trace-abc" />);
    expect(screen.getByText("Issues (2)")).toBeInTheDocument();
  });

  it("shows 'No issues found' when insights list is empty", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    expect(screen.getByText("No issues found.")).toBeInTheDocument();
  });

  it("shows span stats in the sidebar footer", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    expect(screen.getByText("2 spans")).toBeInTheDocument();
    expect(screen.getByText("1 LLM calls")).toBeInTheDocument();
    expect(screen.getByText("1.0s total")).toBeInTheDocument();
  });

  it("shows cycle warning when has_cycle is true", () => {
    render(<TraceDetailClient flow={makeFlow({ has_cycle: true })} insights={[]} traceId="trace-abc" />);
    expect(screen.getByText(/cycle detected/i)).toBeInTheDocument();
  });

  it("does not show cycle warning when has_cycle is false", () => {
    render(<TraceDetailClient flow={makeFlow({ has_cycle: false })} insights={[]} traceId="trace-abc" />);
    expect(screen.queryByText(/cycle detected/i)).not.toBeInTheDocument();
  });

  it("opens span detail drawer when a timeline bar is clicked", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    fireEvent.click(screen.getByRole("button", { name: /timeline/i }));
    fireEvent.click(screen.getByText("llm_call").closest("button")!);
    // Drawer shows span name in header
    const headers = screen.getAllByText("llm_call");
    expect(headers.length).toBeGreaterThan(1); // both timeline row and drawer header
  });

  it("closes span detail drawer when the same span is clicked again", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    fireEvent.click(screen.getByRole("button", { name: /timeline/i }));
    const row = screen.getByText("llm_call").closest("button")!;
    fireEvent.click(row); // open
    fireEvent.click(row); // close (toggle)
    // After second click, drawer should be gone — span name appears only once (in timeline row)
    expect(screen.getAllByText("llm_call")).toHaveLength(1);
  });

  it("shows trace ID in left panel", () => {
    render(<TraceDetailClient flow={makeFlow()} insights={[]} traceId="trace-abc" />);
    expect(screen.getByText("trace-abc")).toBeInTheDocument();
  });

  it("shows 'No spans found' message when flow has no nodes", () => {
    render(
      <TraceDetailClient
        flow={makeFlow({ nodes: [], edges: [], stats: { total_ms: 0, span_count: 0, llm_calls: 0, total_input_tokens: 0, total_output_tokens: 0 } })}
        insights={[]}
        traceId="trace-abc"
      />
    );
    expect(screen.getByText("No spans found for this trace.")).toBeInTheDocument();
  });
});
