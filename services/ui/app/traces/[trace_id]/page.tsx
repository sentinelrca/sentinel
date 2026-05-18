import { getFlow, getTraceInsights, getProjectInsights } from "@/lib/api";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import TraceDetailClient from "./trace-detail-client";

interface Props {
  params: { trace_id: string };
  searchParams: { project_id?: string };
}

export default async function TraceDetailPage({ params, searchParams }: Props) {
  const { trace_id } = params;
  const projectId = searchParams.project_id;

  // When viewing a project trace, fetch flow from project_spans and insights from the project
  const [flowResult, insightsResult] = await Promise.allSettled([
    getFlow(trace_id, projectId),
    projectId ? getProjectInsights(projectId) : getTraceInsights(trace_id),
  ]);

  const flow = flowResult.status === "fulfilled" ? flowResult.value : null;
  const insightsData = insightsResult.status === "fulfilled" ? insightsResult.value : null;
  const insightsError = insightsResult.status === "rejected"
    ? (insightsResult.reason instanceof Error ? insightsResult.reason.message : "Failed to load insights")
    : null;

  // For project mode, filter to only this trace's insights
  const allInsights = insightsData?.items ?? [];
  const insights = projectId
    ? allInsights.filter((i) => i.trace_id === trace_id)
    : allInsights;

  const backHref = projectId ? `/projects/${projectId}` : "/traces";
  const backLabel = projectId ? "Project" : "Traces";

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-slate-200 px-6 py-4">
        <Link
          href={backHref}
          className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
        >
          <ChevronLeft size={16} />
          {backLabel}
        </Link>
        <span className="text-slate-300">/</span>
        <span className="font-mono text-sm text-slate-700">{trace_id}</span>
        {projectId && (
          <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
            Offline Snapshot
          </span>
        )}
      </div>

      {insightsError ? (
        <div className="m-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {insightsError}
        </div>
      ) : (
        <TraceDetailClient
          flow={flow}
          insights={insights}
          traceId={trace_id}
        />
      )}
    </div>
  );
}
