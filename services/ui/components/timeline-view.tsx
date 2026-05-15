"use client";

import { useMemo } from "react";
import { clsx } from "clsx";
import type { FlowNode } from "@/lib/types";

const KIND_BG: Record<string, string> = {
  llm_call:     "bg-violet-400",
  tool_invoke:  "bg-blue-400",
  chain:        "bg-slate-400",
  retrieval:    "bg-green-400",
  agent_invoke: "bg-yellow-400",
};

const MIN_WIDTH_PX = 4;

interface Props {
  nodes: FlowNode[];
  affectedSpanIds: string[];
  selectedSpanId?: string | null;
  onSpanClick?: (span: FlowNode) => void;
  totalMs: number;
}

export default function TimelineView({
  nodes,
  affectedSpanIds,
  selectedSpanId,
  onSpanClick,
  totalMs,
}: Props) {
  const affectedSet = useMemo(() => new Set(affectedSpanIds), [affectedSpanIds]);

  // Sort by duration_ms offset proxy: use node index order (server already orders by start_time)
  // We don't have absolute start_time on the client, so we approximate with the order given.
  // span.duration_ms is the only timing we have; we stack them in the order provided.
  const effective = totalMs > 0 ? totalMs : 1;

  if (nodes.length === 0) return null;

  return (
    <div className="space-y-1 overflow-x-auto">
      {nodes.map((span) => {
        const isAffected = affectedSet.has(span.id);
        const isSelected = selectedSpanId === span.id;
        const widthPct = Math.max(
          MIN_WIDTH_PX,
          Math.round((span.duration_ms / effective) * 100)
        );
        const barColor = isAffected ? "bg-red-400" : (KIND_BG[span.kind] ?? "bg-slate-400");

        return (
          <button
            key={span.id}
            onClick={() => onSpanClick?.(span)}
            className={clsx(
              "flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs transition-colors",
              isSelected ? "bg-blue-50 ring-1 ring-blue-300" : "hover:bg-slate-50",
              isAffected && !isSelected && "bg-red-50"
            )}
          >
            {/* Label */}
            <span
              className={clsx(
                "w-36 shrink-0 truncate font-medium",
                isAffected ? "text-red-700" : "text-slate-700"
              )}
            >
              {span.name || span.id.slice(0, 8)}
            </span>

            {/* Bar track */}
            <div className="relative h-4 flex-1 overflow-hidden rounded bg-slate-100">
              <div
                className={clsx("h-full rounded transition-all", barColor)}
                style={{ width: `${widthPct}%` }}
              />
            </div>

            {/* Duration */}
            <span className="w-14 shrink-0 text-right text-slate-500">
              {span.duration_ms > 0 ? `${span.duration_ms}ms` : "—"}
            </span>
          </button>
        );
      })}
    </div>
  );
}
