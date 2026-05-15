"use client";

import { X } from "lucide-react";
import { formatEvidence } from "@/lib/evidence";
import SeverityBadge from "./severity-badge";
import type { FlowNode, Insight } from "@/lib/types";

interface Props {
  span: FlowNode;
  insights: Insight[];
  onClose: () => void;
}

const KIND_LABEL: Record<string, string> = {
  llm_call:     "LLM Call",
  tool_invoke:  "Tool",
  chain:        "Chain",
  retrieval:    "Retrieval",
  agent_invoke: "Agent",
};

export default function SpanDetailPanel({ span, insights, onClose }: Props) {
  const flaggedBy = insights.filter((i) => i.affected_span_ids.includes(span.id));

  return (
    <div className="flex h-full flex-col overflow-hidden bg-white">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <div className="min-w-0">
          <p className="truncate font-medium text-slate-900">{span.name || span.id}</p>
          <p className="text-xs text-slate-500">{KIND_LABEL[span.kind] ?? span.kind}</p>
        </div>
        <button
          onClick={onClose}
          className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 text-sm">
        {/* Status + identity */}
        <Section title="Identity">
          <Row label="Status">
            <span className={span.status === "error" ? "text-red-600 font-medium" : "text-green-700"}>
              {span.status}
            </span>
          </Row>
          {span.agent_name && <Row label="Agent">{span.agent_name}</Row>}
          {span.model && <Row label="Model">{span.model}</Row>}
        </Section>

        {/* Timing */}
        <Section title="Timing">
          <Row label="Duration">{span.duration_ms > 0 ? `${span.duration_ms}ms` : "—"}</Row>
        </Section>

        {/* Tokens */}
        {((span.input_tokens ?? 0) > 0 || (span.output_tokens ?? 0) > 0) && (
          <Section title="Tokens">
            {(span.input_tokens ?? 0) > 0 && <Row label="Input">{span.input_tokens} tokens</Row>}
            {(span.output_tokens ?? 0) > 0 && <Row label="Output">{span.output_tokens} tokens</Row>}
          </Section>
        )}

        {/* Error */}
        {span.error_message && (
          <Section title="Error">
            <p className="rounded bg-red-50 p-2 text-xs text-red-700 font-mono break-all">
              {span.error_message}
            </p>
          </Section>
        )}

        {/* Retries */}
        {span.retry_count > 0 && (
          <Section title="Retries">
            <span className="inline-flex items-center rounded bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
              {span.retry_count}×
            </span>
          </Section>
        )}

        {/* Flagged by */}
        {flaggedBy.length > 0 && (
          <Section title="Flagged by">
            <div className="space-y-2">
              {flaggedBy.map((ins) => {
                const summary = formatEvidence(ins.rule_id, ins.evidence);
                return (
                  <div key={ins.id} className="rounded border border-slate-200 bg-slate-50 p-2">
                    <div className="flex items-center gap-2">
                      <SeverityBadge severity={ins.severity} />
                      <span className="font-mono text-xs text-slate-700">{ins.rule_id}</span>
                    </div>
                    {summary && (
                      <p className="mt-1 text-xs text-slate-600">{summary}</p>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* Raw attributes */}
        {Object.keys(span.attributes).length > 0 && (
          <Section title="Attributes">
            <div className="space-y-1">
              {Object.entries(span.attributes).map(([k, v]) => (
                <div key={k} className="flex gap-2 text-xs">
                  <span className="shrink-0 font-mono text-slate-500">{k}</span>
                  <span className="min-w-0 break-all text-slate-700">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </span>
                </div>
              ))}
            </div>
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</p>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2 py-0.5">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-900">{children}</span>
    </div>
  );
}
