import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import TimelineView from "@/components/timeline-view";
import type { FlowNode } from "@/lib/types";

function makeSpan(id: string, overrides: Partial<FlowNode> = {}): FlowNode {
  return {
    id,
    name: `span-${id}`,
    kind: "chain",
    status: "ok",
    duration_ms: 500,
    model: null,
    agent_name: null,
    input_tokens: 0,
    output_tokens: 0,
    retry_count: 0,
    parent_id: null,
    error_message: null,
    attributes: {},
    ...overrides,
  };
}

const NODES = [
  makeSpan("s1", { name: "fetch_docs", duration_ms: 300, kind: "retrieval" }),
  makeSpan("s2", { name: "llm_call",   duration_ms: 800, kind: "llm_call" }),
  makeSpan("s3", { name: "tool_exec",  duration_ms: 150, kind: "tool_invoke" }),
];

describe("TimelineView", () => {
  it("renders null when nodes list is empty", () => {
    const { container } = render(
      <TimelineView nodes={[]} affectedSpanIds={[]} totalMs={0} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders a row per span", () => {
    render(<TimelineView nodes={NODES} affectedSpanIds={[]} totalMs={1500} />);
    expect(screen.getByText("fetch_docs")).toBeInTheDocument();
    expect(screen.getByText("llm_call")).toBeInTheDocument();
    expect(screen.getByText("tool_exec")).toBeInTheDocument();
  });

  it("shows duration for each span", () => {
    render(<TimelineView nodes={NODES} affectedSpanIds={[]} totalMs={1500} />);
    expect(screen.getByText("300ms")).toBeInTheDocument();
    expect(screen.getByText("800ms")).toBeInTheDocument();
    expect(screen.getByText("150ms")).toBeInTheDocument();
  });

  it("shows em dash when duration_ms is 0", () => {
    render(
      <TimelineView
        nodes={[makeSpan("s0", { name: "instant", duration_ms: 0 })]}
        affectedSpanIds={[]}
        totalMs={1000}
      />
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("calls onSpanClick with the correct span when a row is clicked", () => {
    const onSpanClick = jest.fn();
    render(
      <TimelineView
        nodes={NODES}
        affectedSpanIds={[]}
        totalMs={1500}
        onSpanClick={onSpanClick}
      />
    );
    fireEvent.click(screen.getByText("llm_call").closest("button")!);
    expect(onSpanClick).toHaveBeenCalledTimes(1);
    expect(onSpanClick.mock.calls[0][0].id).toBe("s2");
  });

  it("applies red styling to affected spans", () => {
    render(
      <TimelineView nodes={NODES} affectedSpanIds={["s1"]} totalMs={1500} />
    );
    const row = screen.getByText("fetch_docs").closest("button")!;
    expect(row).toHaveClass("bg-red-50");
  });

  it("does not apply red styling to unaffected spans", () => {
    render(
      <TimelineView nodes={NODES} affectedSpanIds={["s1"]} totalMs={1500} />
    );
    const row = screen.getByText("llm_call").closest("button")!;
    expect(row).not.toHaveClass("bg-red-50");
  });

  it("applies blue ring to the selected span", () => {
    render(
      <TimelineView
        nodes={NODES}
        affectedSpanIds={[]}
        selectedSpanId="s2"
        totalMs={1500}
      />
    );
    const row = screen.getByText("llm_call").closest("button")!;
    expect(row).toHaveClass("ring-1");
    expect(row).toHaveClass("bg-blue-50");
  });

  it("does not apply blue ring to non-selected spans", () => {
    render(
      <TimelineView
        nodes={NODES}
        affectedSpanIds={[]}
        selectedSpanId="s2"
        totalMs={1500}
      />
    );
    const row = screen.getByText("fetch_docs").closest("button")!;
    expect(row).not.toHaveClass("bg-blue-50");
  });

  it("renders all spans even when totalMs is 0 (avoids division by zero)", () => {
    render(<TimelineView nodes={NODES} affectedSpanIds={[]} totalMs={0} />);
    expect(screen.getByText("fetch_docs")).toBeInTheDocument();
  });
});
