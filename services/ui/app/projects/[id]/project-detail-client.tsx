"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { Download, RefreshCw } from "lucide-react";
import { importProject, analyzeProject, getProject, getProjectTraces } from "@/lib/api";
import { formatDistanceToNow } from "@/lib/date";
import type { Project, TraceSummary } from "@/lib/types";
import TraceCard from "@/components/trace-card";

const POLL_INTERVAL_MS = 3000;

interface Props {
  projectId: string;
  status: Project["status"];
  traceCount: number;
  importCount: number;
  lastAnalyzedAt: string | null;
  initialTraces: TraceSummary[];
}

export default function ProjectDetailClient({
  projectId,
  status: initialStatus,
  traceCount: initialTraceCount,
  importCount: initialImportCount,
  lastAnalyzedAt: initialLastAnalyzedAt,
  initialTraces,
}: Props) {
  const router = useRouter();
  const [status, setStatus] = useState(initialStatus);
  const [traceCount, setTraceCount] = useState(initialTraceCount);
  const [importCount, setImportCount] = useState(initialImportCount);
  const [lastAnalyzedAt, setLastAnalyzedAt] = useState(initialLastAnalyzedAt);
  const [traces, setTraces] = useState<TraceSummary[]>(initialTraces);
  const [importing, setImporting] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prevLastAnalyzedAt = useRef(initialLastAnalyzedAt);

  // Poll while importing or analyzing to keep the UI in sync with the background task.
  // When analysis completes (last_analyzed_at changes), re-fetch the trace list.
  useEffect(() => {
    if (status !== "importing" && status !== "analyzing") return;

    const id = setInterval(async () => {
      try {
        const project = await getProject(projectId);
        const prevAnalyzed = prevLastAnalyzedAt.current;
        setStatus(project.status);
        setTraceCount(project.trace_count);
        setImportCount(project.import_count);
        setLastAnalyzedAt(project.last_analyzed_at);
        prevLastAnalyzedAt.current = project.last_analyzed_at;

        // When analysis completes, reload the trace-grouped insights
        if (
          project.status === "ready" &&
          project.last_analyzed_at !== prevAnalyzed
        ) {
          const traceData = await getProjectTraces(projectId);
          setTraces(traceData.items);
        }
      } catch {
        // ignore transient poll errors — keep polling
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(id);
  }, [status, projectId]);

  async function handleImport() {
    setError(null);
    setImporting(true);
    try {
      await importProject(projectId);
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
      setStatus("analyzing");
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
            {status === "importing" && (
              <span className="text-blue-600">
                Importing traces — this may take a moment…
              </span>
            )}
            {status === "analyzing" && (
              <span className="text-indigo-600">
                Analyzing traces — running rules on your snapshot…
              </span>
            )}
            {status === "pending" && (
              <span>Import traces from your source to enable analysis</span>
            )}
            {status === "ready" && (
              <span>
                {traceCount} trace{traceCount !== 1 ? "s" : ""} imported
                {importCount > 1 && ` · ${importCount} imports total`}
                {lastAnalyzedAt
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

            {status === "analyzing" && (
              <span className="flex items-center gap-2 rounded-md bg-indigo-50 px-3.5 py-2 text-sm font-medium text-indigo-600">
                <RefreshCw size={14} className="animate-spin" />
                Analyzing…
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

      {/* Traces panel */}
      {status === "pending" && (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          Import traces first, then run analysis to see insights.
        </div>
      )}
      {status === "importing" && (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          Waiting for import to complete…
        </div>
      )}
      {status === "analyzing" && (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          Running analysis — results will appear here when complete.
        </div>
      )}
      {status === "error" && (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          Fix the import error above to proceed.
        </div>
      )}
      {status === "ready" && traces.length === 0 && (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          No insights yet. Click &ldquo;Analyze&rdquo; to run analysis on this project.
        </div>
      )}
      {status === "ready" && traces.length > 0 && (
        <div className="space-y-3">
          {traces.map((trace) => (
            <TraceCard
              key={trace.trace_id}
              trace={trace}
              projectId={projectId}
            />
          ))}
        </div>
      )}
    </>
  );
}
