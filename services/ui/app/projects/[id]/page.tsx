import { getProject, getProjectInsights } from "@/lib/api";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import ProjectDetailClient from "./project-detail-client";

interface Props {
  params: { id: string };
}

function filterDescription(filters: { date_from?: string; date_to?: string; trace_ids?: string[] }): string {
  const { date_from, date_to, trace_ids } = filters;

  if (trace_ids && trace_ids.length > 0) {
    return `${trace_ids.length} trace${trace_ids.length !== 1 ? "s" : ""} selected`;
  }

  if (date_from || date_to) {
    const from = date_from ? new Date(date_from).toLocaleDateString() : "…";
    const to = date_to ? new Date(date_to).toLocaleDateString() : "…";
    return `${from} → ${to}`;
  }

  return "All time";
}

export default async function ProjectDetailPage({ params }: Props) {
  const { id } = params;

  const [projectResult, insightsResult] = await Promise.allSettled([
    getProject(id),
    getProjectInsights(id),
  ]);

  const project = projectResult.status === "fulfilled" ? projectResult.value : null;
  const projectError = projectResult.status === "rejected"
    ? (projectResult.reason instanceof Error ? projectResult.reason.message : "Failed to load project")
    : null;

  const insights = insightsResult.status === "fulfilled" ? insightsResult.value : null;
  const insightsError = insightsResult.status === "rejected"
    ? (insightsResult.reason instanceof Error ? insightsResult.reason.message : "Failed to load insights")
    : null;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-slate-200 px-6 py-4">
        <Link
          href="/projects"
          className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
        >
          <ChevronLeft size={16} />
          Projects
        </Link>
        <span className="text-slate-300">/</span>
        <span className="text-sm font-medium text-slate-700">
          {project?.name ?? id}
        </span>
        {project && (
          <>
            <span className="text-slate-300">·</span>
            <span className="text-xs text-slate-500">{filterDescription(project.filters)}</span>
          </>
        )}
      </div>

      <div className="flex-1 overflow-auto p-6">
        {projectError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {projectError}
          </div>
        ) : null}

        {insightsError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {insightsError}
          </div>
        ) : (
          <ProjectDetailClient
            projectId={id}
            status={project?.status ?? "pending"}
            traceCount={project?.trace_count ?? 0}
            importCount={project?.import_count ?? 0}
            lastAnalyzedAt={project?.last_analyzed_at ?? null}
            initialInsights={insights?.items ?? []}
          />
        )}
      </div>
    </div>
  );
}
