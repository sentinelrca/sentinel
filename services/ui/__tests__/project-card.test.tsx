import React from "react";
import { render, screen } from "@testing-library/react";
import ProjectCard from "@/components/project-card";
import type { Project } from "@/lib/types";

jest.mock("next/link", () => {
  const Link = ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
  Link.displayName = "Link";
  return Link;
});

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: "proj-1",
    workspace_id: "ws-1",
    name: "My Project",
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

describe("ProjectCard", () => {
  it("links to the project detail page", () => {
    render(<ProjectCard project={makeProject()} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/projects/proj-1");
  });

  it("displays the project name", () => {
    render(<ProjectCard project={makeProject({ name: "Harry Potter" })} />);
    expect(screen.getByText("Harry Potter")).toBeInTheDocument();
  });

  it("shows Pending status chip", () => {
    render(<ProjectCard project={makeProject({ status: "pending" })} />);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("shows Importing status chip", () => {
    render(<ProjectCard project={makeProject({ status: "importing" })} />);
    expect(screen.getByText("Importing")).toBeInTheDocument();
  });

  it("shows Ready status chip", () => {
    render(<ProjectCard project={makeProject({ status: "ready" })} />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("shows Error status chip", () => {
    render(<ProjectCard project={makeProject({ status: "error" })} />);
    expect(screen.getByText("Error")).toBeInTheDocument();
  });

  it("shows trace count when non-zero", () => {
    render(<ProjectCard project={makeProject({ status: "ready", trace_count: 42 })} />);
    expect(screen.getByText(/42 traces/)).toBeInTheDocument();
  });

  it("hides trace count when zero", () => {
    render(<ProjectCard project={makeProject({ trace_count: 0 })} />);
    expect(screen.queryByText(/traces/)).not.toBeInTheDocument();
  });

  it("shows singular 'trace' when trace_count is 1", () => {
    render(<ProjectCard project={makeProject({ status: "ready", trace_count: 1 })} />);
    const el = screen.getByText(/1 trace/);
    expect(el.textContent).not.toMatch(/traces/);
  });

  it("shows date range filter summary", () => {
    render(
      <ProjectCard
        project={makeProject({
          filters: {
            date_from: "2026-01-01T00:00:00Z",
            date_to: "2026-01-31T00:00:00Z",
          },
        })}
      />
    );
    expect(screen.getByText(/→/)).toBeInTheDocument();
  });

  it("shows trace IDs filter summary", () => {
    render(
      <ProjectCard
        project={makeProject({
          filters: { trace_ids: ["t1", "t2", "t3"] },
        })}
      />
    );
    expect(screen.getByText("3 traces selected")).toBeInTheDocument();
  });

  it("shows 'All time' when no filters set", () => {
    render(<ProjectCard project={makeProject({ filters: {} })} />);
    expect(screen.getByText(/All time/)).toBeInTheDocument();
  });

  it("shows 'Never analyzed' when last_analyzed_at is null", () => {
    render(<ProjectCard project={makeProject({ last_analyzed_at: null })} />);
    expect(screen.getByText("Never analyzed")).toBeInTheDocument();
  });

  it("shows relative time when last_analyzed_at is set", () => {
    const recent = new Date(Date.now() - 3 * 60_000).toISOString();
    render(<ProjectCard project={makeProject({ last_analyzed_at: recent })} />);
    expect(screen.getByText(/ago/)).toBeInTheDocument();
  });
});
