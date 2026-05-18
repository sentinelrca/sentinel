import Link from "next/link";
import { formatDistanceToNow } from "@/lib/date";
import SeverityBadge from "./severity-badge";
import type { TraceSummary } from "@/lib/types";

const MAX_RULES = 4;

export default function TraceCard({
  trace,
  projectId,
}: {
  trace: TraceSummary;
  projectId?: string;
}) {
  const extra = trace.rule_ids.length - MAX_RULES;
  const visibleRules = trace.rule_ids.slice(0, MAX_RULES);
  const href = projectId
    ? `/traces/${trace.trace_id}?project_id=${encodeURIComponent(projectId)}`
    : `/traces/${trace.trace_id}`;

  return (
    <Link
      href={href}
      className="block rounded-lg border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {/* Top row: severity + rule pills */}
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={trace.worst_severity} />
            {visibleRules.map((rule) => (
              <span
                key={rule}
                className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600"
              >
                {rule}
              </span>
            ))}
            {extra > 0 && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-500">
                +{extra} more
              </span>
            )}
          </div>

          {/* Trace ID */}
          <p className="font-mono text-xs text-slate-400">
            trace: {trace.trace_id}
          </p>

          {/* Stats row */}
          <div className="mt-1.5 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>{trace.insight_count} {trace.insight_count === 1 ? "issue" : "issues"}</span>
            {trace.span_count > 0 && <span>{trace.span_count} spans</span>}
            {trace.llm_calls > 0 && <span>{trace.llm_calls} LLM calls</span>}
            {trace.total_ms > 0 && <span>{(trace.total_ms / 1000).toFixed(1)}s</span>}
          </div>
        </div>

        {/* Timestamp */}
        <div className="shrink-0 text-right text-xs text-slate-400">
          {trace.latest_insight_at ? formatDistanceToNow(trace.latest_insight_at) : "—"}
        </div>
      </div>
    </Link>
  );
}
