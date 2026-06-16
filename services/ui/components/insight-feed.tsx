"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import InsightCard from "./insight-card";
import type { Insight } from "@/lib/types";

const SEVERITIES = ["critical", "high", "warning", "info"];
const SEVERITY_LABELS: Record<string, string> = {
  critical: "CRITICAL",
  high: "HIGH",
  warning: "WARNING",
  info: "INFO",
};

interface Props {
  items: Insight[];
  total: number;
  page: number;
  limit: number;
  currentSeverity?: string;
  currentRuleId?: string;
}

export default function InsightFeed({
  items,
  total,
  page,
  limit,
  currentSeverity,
}: Props) {
  const searchParams = useSearchParams();

  function buildUrl(updates: Record<string, string | undefined>) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v === undefined) params.delete(k);
      else params.set(k, v);
    }
    params.delete("page");
    return `/insights?${params.toString()}`;
  }

  const totalPages = Math.ceil(total / limit);

  return (
    <div>
      {/* Severity filter tabs */}
      <div className="mb-4 flex gap-1">
        <Link
          href={buildUrl({ severity: undefined })}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            !currentSeverity
              ? "bg-slate-800 text-white"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          All
        </Link>
        {SEVERITIES.map((s) => (
          <Link
            key={s}
            href={buildUrl({ severity: s })}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              currentSeverity === s
                ? "bg-slate-800 text-white"
                : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {SEVERITY_LABELS[s]}
          </Link>
        ))}
      </div>

      {/* Count */}
      <p className="mb-3 text-sm text-slate-500">
        {total} insight{total !== 1 ? "s" : ""}
      </p>

      {/* List */}
      {items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 py-16 text-center text-sm text-slate-400">
          No insights found
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((insight) => (
            <InsightCard key={insight.id} insight={insight} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="mt-6 flex items-center justify-between text-sm">
          <span className="text-slate-500">
            Page {page} of {totalPages}
          </span>
          <div className="flex gap-2">
            {page > 1 && (
              <Link
                href={buildUrl({ page: String(page - 1) })}
                className="rounded border border-slate-200 bg-white px-3 py-1.5 hover:bg-slate-50"
              >
                Previous
              </Link>
            )}
            {page < totalPages && (
              <Link
                href={buildUrl({ page: String(page + 1) })}
                className="rounded border border-slate-200 bg-white px-3 py-1.5 hover:bg-slate-50"
              >
                Next
              </Link>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
