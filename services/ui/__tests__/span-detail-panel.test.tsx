import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import SpanDetailPanel from "@/components/span-detail-panel";
import type { FlowNode, Insight } from "@/lib/types";

function makeSpan(overrides: Partial<FlowNode> = {}): FlowNode {
  return {
    id: "span-001",
    name: "llm_generate",
    kind: "llm_call",
    status: "ok",
    duration_ms: 1200,
    model: "gpt-4o",
    agent_name: "ResearchAgent",
    input_tokens: 200,
    output_tokens: 80,
    retry_count: 0,
    parent_id: null,
    error_message: null,
    attributes: {},
    ...overrides,
  };
}

function makeInsight(spanId: string, overrides: Partial<Insight> = {}): Insight {
  return {
    id: "ins-001",
    trace_id: "trace-abc",
    rule_id: "retry_storm",
    severity: "high",
    title: "Retry storm detected",
    detail: "detail",
    recommendation: "rec",
    affected_span_ids: [spanId],
    evidence: { retry_count: 5, threshold: 3 },
    status: "open",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("SpanDetailPanel", () => {
  it("shows span name in header", () => {
    render(<SpanDetailPanel span={makeSpan()} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("llm_generate")).toBeInTheDocument();
  });

  it("shows kind label in header", () => {
    render(<SpanDetailPanel span={makeSpan({ kind: "tool_invoke" })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("Tool")).toBeInTheDocument();
  });

  it("shows ok status in green", () => {
    render(<SpanDetailPanel span={makeSpan({ status: "ok" })} insights={[]} onClose={jest.fn()} />);
    const statusEl = screen.getByText("ok");
    expect(statusEl).toHaveClass("text-green-700");
  });

  it("shows error status in red", () => {
    render(<SpanDetailPanel span={makeSpan({ status: "error" })} insights={[]} onClose={jest.fn()} />);
    const statusEl = screen.getByText("error");
    expect(statusEl).toHaveClass("text-red-600");
  });

  it("shows agent name when present", () => {
    render(<SpanDetailPanel span={makeSpan({ agent_name: "PlannerAgent" })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("PlannerAgent")).toBeInTheDocument();
  });

  it("hides agent name when absent", () => {
    render(<SpanDetailPanel span={makeSpan({ agent_name: null })} insights={[]} onClose={jest.fn()} />);
    expect(screen.queryByText("Agent")).not.toBeInTheDocument();
  });

  it("shows model when present", () => {
    render(<SpanDetailPanel span={makeSpan({ model: "claude-3-5-sonnet" })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("claude-3-5-sonnet")).toBeInTheDocument();
  });

  it("shows duration in ms", () => {
    render(<SpanDetailPanel span={makeSpan({ duration_ms: 340 })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("340ms")).toBeInTheDocument();
  });

  it("shows em dash for zero duration", () => {
    render(<SpanDetailPanel span={makeSpan({ duration_ms: 0 })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows input and output token counts", () => {
    render(<SpanDetailPanel span={makeSpan({ input_tokens: 150, output_tokens: 60 })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("150 tokens")).toBeInTheDocument();
    expect(screen.getByText("60 tokens")).toBeInTheDocument();
  });

  it("hides tokens section when both are zero or null", () => {
    render(<SpanDetailPanel span={makeSpan({ input_tokens: 0, output_tokens: 0 })} insights={[]} onClose={jest.fn()} />);
    expect(screen.queryByText(/tokens/)).not.toBeInTheDocument();
  });

  it("shows error message when present", () => {
    render(
      <SpanDetailPanel
        span={makeSpan({ error_message: "Timeout exceeded" })}
        insights={[]}
        onClose={jest.fn()}
      />
    );
    expect(screen.getByText("Timeout exceeded")).toBeInTheDocument();
  });

  it("hides error section when no error", () => {
    render(<SpanDetailPanel span={makeSpan({ error_message: null })} insights={[]} onClose={jest.fn()} />);
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
  });

  it("shows retry count badge when retry_count > 0", () => {
    render(<SpanDetailPanel span={makeSpan({ retry_count: 4 })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("4×")).toBeInTheDocument();
  });

  it("hides retries section when retry_count is 0", () => {
    render(<SpanDetailPanel span={makeSpan({ retry_count: 0 })} insights={[]} onClose={jest.fn()} />);
    expect(screen.queryByText("Retries")).not.toBeInTheDocument();
  });

  it("shows Flagged by section when an insight flags this span", () => {
    const span = makeSpan();
    const insight = makeInsight(span.id);
    render(<SpanDetailPanel span={span} insights={[insight]} onClose={jest.fn()} />);
    expect(screen.getByText("Flagged by")).toBeInTheDocument();
    expect(screen.getByText("retry_storm")).toBeInTheDocument();
  });

  it("shows formatted evidence summary in flagged-by section", () => {
    const span = makeSpan();
    const insight = makeInsight(span.id, { evidence: { retry_count: 5, threshold: 3 } });
    render(<SpanDetailPanel span={span} insights={[insight]} onClose={jest.fn()} />);
    expect(screen.getByText("retried 5× — threshold is 3")).toBeInTheDocument();
  });

  it("does not show Flagged by when no insight flags this span", () => {
    const span = makeSpan({ id: "span-A" });
    const insight = makeInsight("span-B");  // different span
    render(<SpanDetailPanel span={span} insights={[insight]} onClose={jest.fn()} />);
    expect(screen.queryByText("Flagged by")).not.toBeInTheDocument();
  });

  it("shows raw attributes when present", () => {
    const span = makeSpan({ attributes: { "langfuse.type": "generation", "custom.key": "value" } });
    render(<SpanDetailPanel span={span} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("langfuse.type")).toBeInTheDocument();
    expect(screen.getByText("generation")).toBeInTheDocument();
  });

  it("hides attributes section when attributes is empty", () => {
    render(<SpanDetailPanel span={makeSpan({ attributes: {} })} insights={[]} onClose={jest.fn()} />);
    expect(screen.queryByText("Attributes")).not.toBeInTheDocument();
  });

  it("calls onClose when X button is clicked", () => {
    const onClose = jest.fn();
    render(<SpanDetailPanel span={makeSpan()} insights={[]} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows span id when name is empty", () => {
    render(<SpanDetailPanel span={makeSpan({ name: "", id: "abcdef1234567890" })} insights={[]} onClose={jest.fn()} />);
    expect(screen.getByText("abcdef1234567890")).toBeInTheDocument();
  });
});
