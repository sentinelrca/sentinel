import Link from "next/link";
import { formatDistanceToNow } from "@/lib/date";
import SeverityBadge from "./severity-badge";
import type { Insight } from "@/lib/types";

export default function InsightCard({ insight }: { insight: Insight }) {
  return (
    <Link
      href={`/insights/${insight.id}`}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={insight.severity} />
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">
              {insight.detector_id}
            </span>
          </div>
          <p className="truncate text-sm font-medium text-slate-900">{insight.title}</p>
          {insight.detail && (
            <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{insight.detail}</p>
          )}
          <p className="mt-1.5 font-mono text-xs text-slate-400">
            trace: {insight.trace_id}
          </p>
        </div>
        <div className="shrink-0 text-right text-xs text-slate-400">
          {insight.created_at ? formatDistanceToNow(insight.created_at) : "—"}
        </div>
      </div>
    </Link>
  );
}
