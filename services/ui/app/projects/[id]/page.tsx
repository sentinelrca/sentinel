import { getProject, getProjectTraces } from "@/lib/api";
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

  const [projectResult, tracesResult] = await Promise.allSettled([
    getProject(id),
    getProjectTraces(id),
  ]);

  const project = projectResult.status === "fulfilled" ? projectResult.value : null;
  const projectError = projectResult.status === "rejected"
    ? (projectResult.reason instanceof Error ? projectResult.reason.message : "Failed to load project")
    : null;

  const tracesData = tracesResult.status === "fulfilled" ? tracesResult.value : null;
  const tracesError = tracesResult.status === "rejected"
    ? (tracesResult.reason instanceof Error ? tracesResult.reason.message : "Failed to load traces")
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
            <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
              Offline Snapshot
            </span>
          </>
        )}
      </div>

      <div className="flex-1 overflow-auto p-6">
        {projectError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {projectError}
          </div>
        ) : tracesError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {tracesError}
          </div>
        ) : (
          <ProjectDetailClient
            projectId={id}
            status={project?.status ?? "pending"}
            traceCount={project?.trace_count ?? 0}
            importCount={project?.import_count ?? 0}
            lastAnalyzedAt={project?.last_analyzed_at ?? null}
            initialTraces={tracesData?.items ?? []}
          />
        )}
      </div>
    </div>
  );
}
