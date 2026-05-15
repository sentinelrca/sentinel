import React from "react";
import { render, screen } from "@testing-library/react";
import TraceCard from "@/components/trace-card";
import type { TraceSummary } from "@/lib/types";

// next/link renders as <a> in jsdom
jest.mock("next/link", () => {
  const Link = ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
  Link.displayName = "Link";
  return Link;
});

function makeTrace(overrides: Partial<TraceSummary> = {}): TraceSummary {
  return {
    trace_id: "trace-abc123",
    worst_severity: "high",
    insight_count: 2,
    rule_ids: ["retry_storm", "latency_spike"],
    latest_insight_at: new Date(Date.now() - 5 * 60_000).toISOString(), // 5 min ago
    span_count: 10,
    llm_calls: 3,
    total_ms: 1500,
    ...overrides,
  };
}

describe("TraceCard", () => {
  it("links to the trace detail page", () => {
    render(<TraceCard trace={makeTrace()} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/traces/trace-abc123");
  });

  it("displays the trace ID", () => {
    render(<TraceCard trace={makeTrace()} />);
    expect(screen.getByText(/trace-abc123/)).toBeInTheDocument();
  });

  it("shows all rule pills when count <= 4", () => {
    render(<TraceCard trace={makeTrace({ rule_ids: ["retry_storm", "latency_spike"] })} />);
    expect(screen.getByText("retry_storm")).toBeInTheDocument();
    expect(screen.getByText("latency_spike")).toBeInTheDocument();
    expect(screen.queryByText(/more/)).not.toBeInTheDocument();
  });

  it("shows max 4 rule pills and a +N more badge when rule_ids exceeds 4", () => {
    const rule_ids = ["a", "b", "c", "d", "e", "f"];
    render(<TraceCard trace={makeTrace({ rule_ids })} />);
    expect(screen.getByText("a")).toBeInTheDocument();
    expect(screen.getByText("d")).toBeInTheDocument();
    expect(screen.queryByText("e")).not.toBeInTheDocument();
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("shows exactly 4 pills and no overflow badge when rule_ids length is exactly 4", () => {
    const rule_ids = ["a", "b", "c", "d"];
    render(<TraceCard trace={makeTrace({ rule_ids })} />);
    expect(screen.getByText("d")).toBeInTheDocument();
    expect(screen.queryByText(/more/)).not.toBeInTheDocument();
  });

  it("displays insight count with singular form for 1 issue", () => {
    render(<TraceCard trace={makeTrace({ insight_count: 1 })} />);
    expect(screen.getByText(/1 issue/)).toBeInTheDocument();
    expect(screen.queryByText(/issues/)).not.toBeInTheDocument();
  });

  it("displays insight count with plural form for multiple issues", () => {
    render(<TraceCard trace={makeTrace({ insight_count: 3 })} />);
    expect(screen.getByText(/3 issues/)).toBeInTheDocument();
  });

  it("shows span count when non-zero", () => {
    render(<TraceCard trace={makeTrace({ span_count: 19 })} />);
    expect(screen.getByText(/19 spans/)).toBeInTheDocument();
  });

  it("hides span count when zero", () => {
    render(<TraceCard trace={makeTrace({ span_count: 0 })} />);
    expect(screen.queryByText(/spans/)).not.toBeInTheDocument();
  });

  it("shows LLM call count when non-zero", () => {
    render(<TraceCard trace={makeTrace({ llm_calls: 6 })} />);
    expect(screen.getByText(/6 LLM calls/)).toBeInTheDocument();
  });

  it("hides LLM calls when zero", () => {
    render(<TraceCard trace={makeTrace({ llm_calls: 0 })} />);
    expect(screen.queryByText(/LLM calls/)).not.toBeInTheDocument();
  });

  it("shows duration in seconds when total_ms > 0", () => {
    render(<TraceCard trace={makeTrace({ total_ms: 2500 })} />);
    expect(screen.getByText("2.5s")).toBeInTheDocument();
  });

  it("hides duration when total_ms is 0", () => {
    render(<TraceCard trace={makeTrace({ total_ms: 0 })} />);
    expect(screen.queryByText(/^\d+\.\d+s$/)).not.toBeInTheDocument();
  });

  it("shows em dash for missing timestamp", () => {
    render(<TraceCard trace={makeTrace({ latest_insight_at: null })} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows relative timestamp when latest_insight_at is set", () => {
    render(<TraceCard trace={makeTrace()} />);
    // "5m ago" from the 5 minute offset in makeTrace
    expect(screen.getByText(/ago/)).toBeInTheDocument();
  });
});
