import React from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectDetailClient from "@/app/projects/[id]/project-detail-client";
import type { Project, TraceSummary } from "@/lib/types";

jest.mock("next/navigation", () => ({
  useRouter: jest.fn(() => ({ refresh: jest.fn() })),
}));

jest.mock("@/lib/api", () => ({
  importProject: jest.fn(),
  analyzeProject: jest.fn(),
  getProject: jest.fn(),
  getProjectTraces: jest.fn(),
}));

jest.mock("@/components/trace-card", () => {
  const TraceCard = ({ trace }: { trace: TraceSummary }) => (
    <div data-testid="trace-card">{trace.trace_id}</div>
  );
  TraceCard.displayName = "TraceCard";
  return TraceCard;
});

import { importProject, analyzeProject, getProject, getProjectTraces } from "@/lib/api";
import { useRouter } from "next/navigation";

const mockImportProject = importProject as jest.MockedFunction<typeof importProject>;
const mockAnalyzeProject = analyzeProject as jest.MockedFunction<typeof analyzeProject>;
const mockGetProject = getProject as jest.MockedFunction<typeof getProject>;
const mockGetProjectTraces = getProjectTraces as jest.MockedFunction<typeof getProjectTraces>;
const mockUseRouter = useRouter as jest.MockedFunction<typeof useRouter>;

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

function makeTrace(overrides: Partial<TraceSummary> = {}): TraceSummary {
  return {
    trace_id: "trace-1",
    worst_severity: "high",
    insight_count: 2,
    rule_ids: ["retry_storm"],
    latest_insight_at: new Date().toISOString(),
    span_count: 5,
    llm_calls: 2,
    total_ms: 1200,
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
    initialTraces: [],
    ...overrides,
  };
}

let mockRefresh: jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockRefresh = jest.fn();
  mockUseRouter.mockReturnValue({ refresh: mockRefresh } as ReturnType<typeof useRouter>);
  // Default: never resolves — prevents accidental polls completing in non-polling tests
  mockGetProject.mockImplementation(() => new Promise(() => {}));
  mockGetProjectTraces.mockImplementation(() => new Promise(() => {}));
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

  it("shows analyzing message when status is analyzing", () => {
    render(<ProjectDetailClient {...baseProps({ status: "analyzing" })} />);
    expect(screen.getByText(/Analyzing traces/)).toBeInTheDocument();
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

  it("shows Analyzing spinner and no Analyze button when status is analyzing", () => {
    render(<ProjectDetailClient {...baseProps({ status: "analyzing" })} />);
    expect(screen.getByText(/Analyzing…/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Analyze/ })).not.toBeInTheDocument();
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

  it("polls getProject every 3s while status is analyzing", async () => {
    mockGetProject.mockResolvedValue(makeProject({ status: "analyzing" }));
    render(<ProjectDetailClient {...baseProps({ status: "analyzing" })} />);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });
    expect(mockGetProject).toHaveBeenCalledTimes(1);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });
    expect(mockGetProject).toHaveBeenCalledTimes(2);
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

  it("transitions to ready and stops polling when import completes", async () => {
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
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });

    await waitFor(() => {
      expect(screen.getByText(/10 traces imported/)).toBeInTheDocument();
    });
  });

  it("polling starts automatically when page loads with analyzing status", async () => {
    mockGetProject.mockResolvedValueOnce(
      makeProject({ status: "ready", trace_count: 7, import_count: 1, last_analyzed_at: new Date().toISOString() })
    );
    mockGetProjectTraces.mockResolvedValueOnce({ items: [], total: 0 });
    render(<ProjectDetailClient {...baseProps({ status: "analyzing" })} />);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });

    await waitFor(() => {
      expect(screen.getByText(/7 traces imported/)).toBeInTheDocument();
    });
  });

  it("re-fetches traces when analysis completes (last_analyzed_at changes)", async () => {
    const analyzedAt = new Date().toISOString();
    mockGetProject.mockResolvedValueOnce(
      makeProject({ status: "ready", trace_count: 3, import_count: 1, last_analyzed_at: analyzedAt })
    );
    const newTrace = makeTrace({ trace_id: "trace-abc" });
    mockGetProjectTraces.mockResolvedValueOnce({ items: [newTrace], total: 1 });

    // Start with analyzing status and no previous last_analyzed_at
    render(<ProjectDetailClient {...baseProps({ status: "analyzing", lastAnalyzedAt: null })} />);

    await act(async () => { await jest.advanceTimersByTimeAsync(3000); });

    await waitFor(() => {
      expect(mockGetProjectTraces).toHaveBeenCalledWith("proj-1");
      expect(screen.getByTestId("trace-card")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Analyze flow
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — Analyze flow", () => {
  it("calls analyzeProject and transitions to analyzing state on success", async () => {
    mockAnalyzeProject.mockResolvedValueOnce({ task_id: "task-2" });
    render(<ProjectDetailClient {...baseProps({ status: "ready" })} />);

    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));

    expect(mockAnalyzeProject).toHaveBeenCalledWith("proj-1");
    await waitFor(() => {
      expect(screen.getByText(/Analyzing traces/)).toBeInTheDocument();
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
// Traces panel
// ---------------------------------------------------------------------------

describe("ProjectDetailClient — traces panel", () => {
  it("shows empty state when status is pending", () => {
    render(<ProjectDetailClient {...baseProps({ status: "pending" })} />);
    expect(screen.getByText(/Import traces first/)).toBeInTheDocument();
  });

  it("shows waiting message when status is importing", () => {
    render(<ProjectDetailClient {...baseProps({ status: "importing" })} />);
    expect(screen.getByText(/Waiting for import to complete/)).toBeInTheDocument();
  });

  it("shows analyzing message panel when status is analyzing", () => {
    render(<ProjectDetailClient {...baseProps({ status: "analyzing" })} />);
    expect(screen.getByText(/Running analysis/)).toBeInTheDocument();
  });

  it("shows 'No insights yet' when ready with no traces", () => {
    render(<ProjectDetailClient {...baseProps({ status: "ready", initialTraces: [] })} />);
    expect(screen.getByText(/No insights yet/)).toBeInTheDocument();
  });

  it("renders trace cards when traces are present", () => {
    const traces = [
      makeTrace({ trace_id: "trace-1" }),
      makeTrace({ trace_id: "trace-2" }),
    ];
    render(<ProjectDetailClient {...baseProps({ status: "ready", initialTraces: traces })} />);
    expect(screen.getAllByTestId("trace-card")).toHaveLength(2);
    expect(screen.getByText("trace-1")).toBeInTheDocument();
    expect(screen.getByText("trace-2")).toBeInTheDocument();
  });
});
