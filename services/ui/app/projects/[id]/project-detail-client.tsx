"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import InsightCard from "@/components/insight-card";
import { analyzeProject } from "@/lib/api";
import { formatDistanceToNow } from "@/lib/date";
import type { Insight } from "@/lib/types";

interface Props {
  projectId: string;
  projectName: string;
  lastAnalyzedAt: string | null;
  initialInsights: Insight[];
}

export default function ProjectDetailClient({
  projectId,
  projectName,
  lastAnalyzedAt,
  initialInsights,
}: Props) {
  const [analyzing, setAnalyzing] = useState(false);
  const [queued, setQueued] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAnalyze() {
    setError(null);
    setAnalyzing(true);
    try {
      await analyzeProject(projectId);
      // Give the user feedback; a full re-fetch would require router.refresh() in a page context.
      // We show the "queued" message and let the user refresh manually.
      setTimeout(() => {
        setAnalyzing(false);
        setQueued(true);
      }, 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
      setAnalyzing(false);
    }
  }

  return (
    <>
      {/* Action bar */}
      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="text-xs text-slate-500">
          {queued
            ? "Analysis queued — refresh in a moment to see new insights"
            : lastAnalyzedAt
            ? `Last analyzed ${formatDistanceToNow(lastAnalyzedAt)}`
            : "Not yet analyzed"}
        </div>
        <button
          onClick={handleAnalyze}
          disabled={analyzing}
          className="flex items-center gap-2 rounded-md bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors disabled:opacity-60"
        >
          <RefreshCw size={14} className={analyzing ? "animate-spin" : ""} />
          {analyzing ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {initialInsights.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          No insights yet. Click &ldquo;Analyze&rdquo; to run analysis on this project.
        </div>
      ) : (
        <div className="space-y-3">
          {initialInsights.map((insight) => (
            <InsightCard key={insight.id} insight={insight} />
          ))}
        </div>
      )}
    </>
  );
}
