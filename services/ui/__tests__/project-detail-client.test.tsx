import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectDetailClient from "@/app/projects/[id]/project-detail-client";
import type { Insight, Project } from "@/lib/types";

jest.mock("@/lib/api", () => ({
  importProject: jest.fn(),
  analyzeProject: jest.fn(),
  getProject: jest.fn(),
}));

jest.mock("@/components/insight-card", () => {
  const InsightCard = ({ insight }: { insight: Insight }) => (
    <div data-testid="insight-card">{insight.title}</div>
  );
  InsightCard.displayName = "InsightCard";
  return InsightCard;
});

import { importProject, analyzeProject, getProject } from "@/lib/api";

const mockImportProject = importProject as jest.MockedFunction<typeof importProject>;
const mockAnalyzeProject = analyzeProject as jest.MockedFunction<typeof analyzeProject>;
const mockGetProject = getProject as jest.MockedFunction<typeof getProject>;

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "proj-1",
    workspace_id: "ws-1",
    name: "Test",
    filters: {},
    status: "pending",
    trace_count: 0,
    import_count: 0,
    created_at: new Date().toISOString(),
    last_imported_at: null,
    last_analyzed_at: null,
    ...overrides,
  };
}

function baseProps(overrides = {}) {
  return {
    projectId: "proj-1",
    status: "pending" as const,
    traceCount: 0,
    importCount: 0,
    lastAnalyzedAt: null,
    initialInsights: [],
    ...overrides,
  };
}

function makeInsight(overrides: Partial<Insight> = {}): Insight {
  return {
    id: "ins-1",
    trace_id: "trace-1",
    rule_id: "retry_storm",
    severity: "high",
    title: "Retry Storm Detected",
    detail: "details",
    recommendation: "fix it",
    affected_span_ids: [],
    evidence: null,
    status: "OPEN",
    created_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  // Default: never resolves — prevents accidental polls completing in non-polling tests
  mockGetProject.mockImplementation(() => new Promise(() => {}));
});

// ---------------------------------------------------------------------------
// Status messages
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — status messages", () => {
  it("shows import hint when status is pending", () => {
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);
    expect(screen.getByText(/Import traces from your source/)).toBeInTheDocument();
  });

  it("shows importing message when status is importing", () => {
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);
    expect(screen.getByText(/Importing traces/)).toBeInTheDocument();
  });

  it("shows error message when status is error", () => {
    render(<ProjectDetailClient {...baseProps({ status: "error" })} />);
    expect(screen.getByText(/check your source configuration/)).toBeInTheDocument();
  });

  it("shows trace count and last analyzed when status is ready", () => {
    const lastAnalyzedAt = new Date(Date.now() - 2 * 60_000).toISOString();
    render(
      <ProjectDetailClient
        {...baseProps({ status: "ready", traceCount: 5, importCount: 1, lastAnalyzedAt })}
      />
    );
    expect(screen.getByText(/5 traces imported/)).toBeInTheDocument();
    expect(screen.getByText(/Last analyzed/)).toBeInTheDocument();
  });

  it("shows 'Not yet analyzed' when ready but lastAnalyzedAt is null", () => {
    render(
      <ProjectDetailClient
        {...baseProps({ status: "ready", traceCount: 3, importCount: 1, lastAnalyzedAt: null })}
      />
    );
    expect(screen.getByText(/Not yet analyzed/)).toBeInTheDocument();
  });

  it("shows imports total only when importCount > 1", () => {
    render(
      <ProjectDetailClient
        {...baseProps({ status: "ready", traceCount: 3, importCount: 2, lastAnalyzedAt: null })}
      />
    );
    expect(screen.getByText(/2 imports total/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Action buttons
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — action buttons", () => {
  it("shows Import button when status is pending", () => {
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);
    expect(screen.getByRole("button", { name: /Import/ })).toBeInTheDocument();
  });

  it("shows Retry Import button when status is error", () => {
    render(<ProjectDetailClient {...baseProps({ status: "error" })} />);
    expect(screen.getByRole("button", { name: /Retry Import/ })).toBeInTheDocument();
  });

  it("shows Analyze button when status is ready", () => {
    render(<ProjectDetailClient {...baseProps({ status: "ready" })} />);
    expect(screen.getByRole("button", { name: /Analyze/ })).toBeInTheDocument();
  });

  it("shows Re-analyze when status is ready with prior imports and analysis", () => {
    render(
      <ProjectDetailClient
        {...baseProps({
          status: "ready",
          importCount: 1,
          lastAnalyzedAt: new Date().toISOString(),
        })}
      />
    );
    expect(screen.getByRole("button", { name: /Re-analyze/ })).toBeInTheDocument();
  });

  it("shows Importing spinner and no Import button when status is importing", () => {
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);
    expect(screen.getByText(/Importing…/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Import$/ })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Import flow
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — Import flow", () => {
  it("calls importProject and transitions to importing state on success", async () => {
    mockImportProject.mockResolvedValueOnce({ task_id: "task-1" });
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Import/ }));

    expect(mockImportProject).toHaveBeenCalledWith("proj-1");
    await waitFor(() => {
      expect(screen.getByText(/Importing traces/)).toBeInTheDocument();
    });
  });

  it("shows error message when importProject fails", async () => {
    mockImportProject.mockRejectedValueOnce(new Error("Network error"));
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Import/ }));

    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("shows fallback error message for non-Error rejections", async () => {
    mockImportProject.mockRejectedValueOnce("oops");
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Import/ }));

    await waitFor(() => {
      expect(screen.getByText("Failed to start import")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Polling (fake timers scoped to this block)
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — polling while importing", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  it("polls getProject every 3s while status is importing", async () => {
    mockGetProject.mockResolvedValue(makeProject({ status: "importing" }));
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });
    expect(mockGetProject).toHaveBeenCalledTimes(1);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });
    expect(mockGetProject).toHaveBeenCalledTimes(2);

    expect(mockGetProject).toHaveBeenCalledWith("proj-1");
  });

  it("does not poll when status is pending", async () => {
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);
    await jest.advanceTimersByTimeAsync(9000);
    expect(mockGetProject).not.toHaveBeenCalled();
  });

  it("does not poll when status is ready", async () => {
    render(<ProjectDetailClient {...baseProps({ status: "ready" })} />);
    await jest.advanceTimersByTimeAsync(9000);
    expect(mockGetProject).not.toHaveBeenCalled();
  });

  it("transitions to ready and stops polling when task completes", async () => {
    mockGetProject
      .mockResolvedValueOnce(makeProject({ status: "importing" }))
      .mockResolvedValueOnce(makeProject({ status: "ready", trace_count: 42, import_count: 1 }));

    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);

    // First poll — still importing
    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText(/Importing traces/)).toBeInTheDocument();

    // Second poll — ready
    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });
    await waitFor(() => {
      expect(screen.getByText(/42 traces imported/)).toBeInTheDocument();
    });

    // No further polls after reaching ready
    const callCount = mockGetProject.mock.calls.length;
    await jest.advanceTimersByTimeAsync(6000);
    expect(mockGetProject).toHaveBeenCalledTimes(callCount);
  });

  it("transitions to error state when import fails in the background", async () => {
    mockGetProject.mockResolvedValueOnce(makeProject({ status: "error" }));
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });

    await waitFor(() => {
      expect(screen.getByText(/check your source configuration/)).toBeInTheDocument();
    });
  });

  it("ignores transient poll errors and keeps polling until success", async () => {
    mockGetProject
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValueOnce(makeProject({ status: "ready", trace_count: 5, import_count: 1 }));

    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);

    // First poll — network error, state unchanged
    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });

    // Second poll — success
    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });
    await waitFor(() => {
      expect(screen.getByText(/5 traces imported/)).toBeInTheDocument();
    });
  });

  it("polling starts automatically when page loads with importing status", async () => {
    mockGetProject.mockResolvedValueOnce(makeProject({ status: "ready", trace_count: 10, import_count: 1 }));
    // Simulates navigating back to a page where the import was already in progress
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });

    await waitFor(() => {
      expect(screen.getByText(/10 traces imported/)).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Analyze flow
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — Analyze flow", () => {
  it("calls analyzeProject and shows queued message on success", async () => {
    mockAnalyzeProject.mockResolvedValueOnce({ task_id: "task-2" });
    render(<ProjectDetailClient {...baseProps({ status: "ready" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));

    expect(mockAnalyzeProject).toHaveBeenCalledWith("proj-1");
    await waitFor(() => {
      expect(screen.getByText(/Analysis queued/)).toBeInTheDocument();
    });
  });

  it("shows error message when analyzeProject fails", async () => {
    mockAnalyzeProject.mockRejectedValueOnce(new Error("Service unavailable"));
    render(<ProjectDetailClient {...baseProps({ status: "ready" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));

    await waitFor(() => {
      expect(screen.getByText("Service unavailable")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Insights panel
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — insights panel", () => {
  it("shows empty state when status is pending", () => {
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);
    expect(screen.getByText(/Import traces first/)).toBeInTheDocument();
  });

  it("shows waiting message when status is importing", () => {
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);
    expect(screen.getByText(/Waiting for import to complete/)).toBeInTheDocument();
  });

  it("shows 'No insights yet' when ready with no insights", () => {
    render(<ProjectDetailClient {...baseProps({ status: "ready", initialInsights: [] })} />);
    expect(screen.getByText(/No insights yet/)).toBeInTheDocument();
  });

  it("renders insight cards when insights are present", () => {
    const insights = [
      makeInsight({ id: "ins-1", title: "Retry Storm Detected" }),
      makeInsight({ id: "ins-2", title: "Latency Spike" }),
    ];
    render(<ProjectDetailClient {...baseProps({ status: "ready", initialInsights: insights })} />);
    expect(screen.getAllByTestId("insight-card")).toHaveLength(2);
    expect(screen.getByText("Retry Storm Detected")).toBeInTheDocument();
    expect(screen.getByText("Latency Spike")).toBeInTheDocument();
  });

  it("shows insights panel when analyzeQueued is true", async () => {
    mockAnalyzeProject.mockResolvedValueOnce({ task_id: "task-2" });
    render(<ProjectDetailClient {...baseProps({ status: "ready", initialInsights: [] })} />);

    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));

    await waitFor(() => {
      expect(screen.getByText(/No insights yet/)).toBeInTheDocument();
    });
  });
});
