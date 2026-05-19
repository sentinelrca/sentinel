"use client";

import Link from "next/link";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { deleteProject } from "@/lib/api";
import { formatDistanceToNow } from "@/lib/date";
import type { Project } from "@/lib/types";

const STATUS_CONFIG: Record<
  Project["status"],
  { label: string; className: string }
> = {
  pending:   { label: "Pending",   className: "bg-slate-100 text-slate-600" },
  importing: { label: "Importing", className: "bg-blue-100 text-blue-700 animate-pulse" },
  analyzing: { label: "Analyzing", className: "bg-indigo-100 text-indigo-700 animate-pulse" },
  ready:     { label: "Ready",     className: "bg-green-100 text-green-700" },
  error:     { label: "Error",     className: "bg-red-100 text-red-700" },
};

function StatusChip({ status }: { status: Project["status"] }) {
  const { label, className } = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending;
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${className}`}>
      {label}
    </span>
  );
}

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

export default function ProjectCard({
  project,
  onDeleted,
}: {
  project: Project;
  onDeleted?: (id: string) => void;
}) {
  const [deleting, setDeleting] = useState(false);

  async function handleDelete(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete project "${project.name}"? This will remove all imported spans and insights.`)) return;
    setDeleting(true);
    try {
      await deleteProject(project.id);
      onDeleted?.(project.id);
    } catch {
      alert("Failed to delete project — please try again.");
      setDeleting(false);
    }
  }

  return (
    <Link
      href={`/projects/${project.id}`}
      className="group block rounded-lg border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium text-slate-900">{project.name}</p>
            <StatusChip status={project.status} />
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {filterSummary(project)}
            {project.trace_count > 0 && ` · ${project.trace_count} trace${project.trace_count !== 1 ? "s" : ""}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-right text-xs text-slate-400">
            {project.last_analyzed_at
              ? formatDistanceToNow(project.last_analyzed_at)
              : "Never analyzed"}
          </span>
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="rounded p-1 text-slate-300 opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100 disabled:opacity-40"
            title="Delete project"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </Link>
  );
}
