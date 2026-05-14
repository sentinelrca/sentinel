import { getInsight, getFlow } from "@/lib/api";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";
import SeverityBadge from "@/components/severity-badge";
import FlowGraph from "@/components/flow-graph";

interface Props {
  params: { id: string };
}

export default async function InsightDetailPage({ params }: Props) {
  let insight;
  let flow;
  let insightError: string | null = null;
  let flowError: string | null = null;

  try {
    insight = await getInsight(params.id);
  } catch (e) {
    insightError = e instanceof Error ? e.message : "Failed to load insight";
  }

  if (insight) {
    try {
      flow = await getFlow(insight.trace_id);
    } catch (e) {
      flowError = e instanceof Error ? e.message : "Flow graph unavailable";
    }
  }

  if (insightError || !insight) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {insightError ?? "Insight not found"}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl">
      <Link
        href="/insights"
        className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700"
      >
        <ChevronLeft size={14} /> Back to insights
      </Link>

      {/* Header */}
      <div className="mb-6 flex items-start gap-3">
        <SeverityBadge severity={insight.severity} size="lg" />
        <div>
          <h1 className="text-xl font-semibold text-slate-900">{insight.title}</h1>
          <p className="mt-0.5 text-sm text-slate-500">
            Rule: <span className="font-mono">{insight.rule_id}</span> &middot; Trace:{" "}
            <span className="font-mono">{insight.trace_id}</span>
          </p>
        </div>
      </div>

      {/* Detail + Recommendation */}
      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Detail
          </h2>
          <p className="text-sm text-slate-700">{insight.detail}</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Recommendation
          </h2>
          <p className="text-sm text-slate-700">{insight.recommendation}</p>
        </div>
      </div>

      {/* Evidence */}
      {insight.evidence && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
            Evidence
          </h2>
          <pre className="overflow-x-auto text-xs text-slate-600">
            {JSON.stringify(insight.evidence, null, 2)}
          </pre>
        </div>
      )}

      {/* Flow Graph */}
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Flow Graph
        </h2>
        {flowError ? (
          <p className="text-sm text-slate-400">{flowError}</p>
        ) : flow ? (
          <>
            <div className="mb-3 flex flex-wrap gap-4 text-xs text-slate-500">
              <span>{flow.stats.span_count} spans</span>
              <span>{flow.stats.llm_calls} LLM calls</span>
              <span>{(flow.stats.total_ms / 1000).toFixed(1)}s total</span>
              {flow.has_cycle && (
                <span className="font-medium text-amber-600">cycle detected</span>
              )}
            </div>
            <FlowGraph
              nodes={flow.nodes}
              edges={flow.edges}
              affectedSpanIds={insight.affected_span_ids}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}
