import Link from "next/link";
import { formatDistanceToNow } from "@/lib/date";
import type { Project } from "@/lib/types";

function filterSummary(project: Project): string {
  const { date_from, date_to, trace_ids } = project.filters;

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

export default function ProjectCard({ project }: { project: Project }) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900">{project.name}</p>
          <p className="mt-1 text-xs text-slate-500">{filterSummary(project)}</p>
        </div>
        <div className="shrink-0 text-right text-xs text-slate-400">
          {project.last_analyzed_at
            ? formatDistanceToNow(project.last_analyzed_at)
            : "Never analyzed"}
        </div>
      </div>
    </Link>
  );
}
