"use client";

import { useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import InsightCard from "@/components/insight-card";
import { importProject, analyzeProject } from "@/lib/api";
import { formatDistanceToNow } from "@/lib/date";
import type { Insight, Project } from "@/lib/types";

interface Props {
  projectId: string;
  status: Project["status"];
  traceCount: number;
  importCount: number;
  lastAnalyzedAt: string | null;
  initialInsights: Insight[];
}

export default function ProjectDetailClient({
  projectId,
  status: initialStatus,
  traceCount,
  importCount,
  lastAnalyzedAt,
  initialInsights,
}: Props) {
  const [status, setStatus] = useState(initialStatus);
  const [importing, setImporting] = useState(false);
  const [importQueued, setImportQueued] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeQueued, setAnalyzeQueued] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleImport() {
    setError(null);
    setImporting(true);
    try {
      await importProject(projectId);
      setImportQueued(true);
      setStatus("importing");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start import");
    } finally {
      setImporting(false);
    }
  }

  async function handleAnalyze() {
    setError(null);
    setAnalyzing(true);
    try {
      await analyzeProject(projectId);
      setAnalyzeQueued(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setAnalyzing(false);
    }
  }

  return (
    <>
      {/* Action bar */}
      <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex items-center justify-between gap-4">
          {/* Left: status info */}
          <div className="text-xs text-slate-500">
            {status === "importing" && !importQueued && (
              <span className="text-blue-600">Importing traces — refresh in a moment once complete</span>
            )}
            {status === "pending" && !importQueued && (
              <span>Import traces from your source to enable analysis</span>
            )}
            {importQueued && status === "importing" && (
              <span className="text-blue-600">Import queued — refresh once importing completes</span>
            )}
            {status === "ready" && (
              <span>
                {traceCount} trace{traceCount !== 1 ? "s" : ""} imported
                {importCount > 1 && ` · ${importCount} imports total`}
                {analyzeQueued
                  ? " · Analysis queued — refresh in a moment"
                  : lastAnalyzedAt
                  ? ` · Last analyzed ${formatDistanceToNow(lastAnalyzedAt)}`
                  : " · Not yet analyzed"}
              </span>
            )}
            {status === "error" && (
              <span className="text-red-600">Import failed — check your source configuration and retry</span>
            )}
          </div>

          {/* Right: action buttons */}
          <div className="flex shrink-0 items-center gap-2">
            {(status === "pending" || status === "error") && (
              <button
                onClick={handleImport}
                disabled={importing}
                className="flex items-center gap-2 rounded-md bg-blue-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors disabled:opacity-60"
              >
                <Download size={14} className={importing ? "animate-bounce" : ""} />
                {importing ? "Starting…" : status === "error" ? "Retry Import" : "Import"}
              </button>
            )}

            {status === "ready" && (
              <button
                onClick={handleAnalyze}
                disabled={analyzing}
                className="flex items-center gap-2 rounded-md bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700 transition-colors disabled:opacity-60"
              >
                <RefreshCw size={14} className={analyzing ? "animate-spin" : ""} />
                {analyzing ? "Analyzing…" : importCount > 0 && lastAnalyzedAt ? "Re-analyze" : "Analyze"}
              </button>
            )}

            {status === "importing" && (
              <span className="flex items-center gap-2 rounded-md bg-blue-50 px-3.5 py-2 text-sm font-medium text-blue-600">
                <RefreshCw size={14} className="animate-spin" />
                Importing…
              </span>
            )}
          </div>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {status !== "ready" && !analyzeQueued ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          {status === "pending" && "Import traces first, then run analysis to see insights."}
          {status === "importing" && "Waiting for import to complete…"}
          {status === "error" && "Fix the import error above to proceed."}
        </div>
      ) : initialInsights.length === 0 ? (
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
