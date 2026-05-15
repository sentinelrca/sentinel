"use client";

import { useState } from "react";
import FlowGraphCanvas from "@/components/flow-graph";
import TimelineView from "@/components/timeline-view";
import SpanDetailPanel from "@/components/span-detail-panel";
import SeverityBadge from "@/components/severity-badge";
import { clsx } from "clsx";
import type { FlowGraph, FlowNode, Insight } from "@/lib/types";

interface Props {
  flow: FlowGraph | null;
  insights: Insight[];
  traceId: string;
}

export default function TraceDetailClient({ flow, insights, traceId }: Props) {
  const [selectedInsightId, setSelectedInsightId] = useState<string | null>(
    insights[0]?.id ?? null
  );
  const [selectedSpan, setSelectedSpan] = useState<FlowNode | null>(null);
  const [activeTab, setActiveTab] = useState<"graph" | "timeline">("graph");

  const selectedInsight = insights.find((i) => i.id === selectedInsightId) ?? null;
  const affectedSpanIds = selectedInsight?.affected_span_ids ?? [];

  function handleSpanClick(span: FlowNode) {
    setSelectedSpan((prev) => (prev?.id === span.id ? null : span));
  }

  return (
    <div className="flex min-h-0 flex-1 overflow-hidden">
      {/* Left panel — issues list */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-3">
          <p className="text-sm font-semibold text-slate-700">
            Issues ({insights.length})
          </p>
          <p className="mt-0.5 text-xs text-slate-400 font-mono truncate">{traceId}</p>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {insights.length === 0 ? (
            <p className="px-4 py-3 text-xs text-slate-400">No issues found.</p>
          ) : (
            insights.map((ins) => (
              <button
                key={ins.id}
                onClick={() => setSelectedInsightId(ins.id)}
                className={clsx(
                  "w-full px-4 py-2.5 text-left transition-colors",
                  selectedInsightId === ins.id
                    ? "bg-slate-100"
                    : "hover:bg-slate-50"
                )}
              >
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={ins.severity} />
                </div>
                <p className="mt-1 font-mono text-xs text-slate-700">{ins.rule_id}</p>
                <p className="mt-0.5 text-xs text-slate-500 line-clamp-2">{ins.title}</p>
              </button>
            ))
          )}
        </div>

        {/* Stats */}
        {flow && (
          <div className="border-t border-slate-200 px-4 py-3 text-xs text-slate-500 space-y-0.5">
            {flow.stats.span_count > 0 && <p>{flow.stats.span_count} spans</p>}
            {flow.stats.llm_calls > 0 && <p>{flow.stats.llm_calls} LLM calls</p>}
            {flow.stats.total_ms > 0 && <p>{(flow.stats.total_ms / 1000).toFixed(1)}s total</p>}
            {flow.has_cycle && (
              <p className="text-orange-600 font-medium">⚠ cycle detected</p>
            )}
          </div>
        )}
      </aside>

      {/* Center — graph / timeline + drawer */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Tab bar */}
        <div className="flex border-b border-slate-200 bg-white px-4">
          {(["graph", "timeline"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={clsx(
                "px-4 py-2.5 text-sm font-medium capitalize transition-colors",
                activeTab === tab
                  ? "border-b-2 border-indigo-500 text-indigo-600"
                  : "text-slate-500 hover:text-slate-700"
              )}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-4">
          {!flow ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-sm text-slate-500">
              Flow graph unavailable — span data was not found in ClickHouse.
              This trace may have been ingested before the current sync window.
            </div>
          ) : activeTab === "graph" ? (
            flow.nodes.length === 0 ? (
              <p className="text-sm text-slate-500">No spans found for this trace.</p>
            ) : (
              <FlowGraphCanvas
                nodes={flow.nodes}
                edges={flow.edges}
                affectedSpanIds={affectedSpanIds}
                allInsights={insights}
                selectedSpanId={selectedSpan?.id ?? null}
                onNodeClick={handleSpanClick}
              />
            )
          ) : (
            <TimelineView
              nodes={flow.nodes}
              affectedSpanIds={affectedSpanIds}
              selectedSpanId={selectedSpan?.id ?? null}
              onSpanClick={handleSpanClick}
              totalMs={flow.stats.total_ms}
            />
          )}
        </div>

        {/* Span detail drawer (slides in from right) */}
        {selectedSpan && (
          <div className="absolute inset-y-0 right-0 w-80 border-l border-slate-200 shadow-lg">
            <SpanDetailPanel
              span={selectedSpan}
              insights={insights}
              onClose={() => setSelectedSpan(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
