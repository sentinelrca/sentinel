"use client";

import { useEffect, useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";
import { clsx } from "clsx";

const SEVERITIES = ["critical", "high", "warning", "info"] as const;

interface Props {
  insightId: string;
  ruleId: string;
  currentSeverity: string;
  onIgnoreInstance: (id: string) => void;
  onIgnoreRule: (ruleId: string) => void;
  onChangeSeverity: (id: string, severity: string, applyToAll: boolean) => void;
}

export default function IssueActionMenu({
  insightId,
  ruleId,
  currentSeverity,
  onIgnoreInstance,
  onIgnoreRule,
  onChangeSeverity,
}: Props) {
  const [open, setOpen] = useState(false);
  const [applyToAll, setApplyToAll] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  function handleIgnoreInstance() {
    setOpen(false);
    onIgnoreInstance(insightId);
  }

  function handleIgnoreRule() {
    setOpen(false);
    onIgnoreRule(ruleId);
  }

  function handleSeverity(sev: string) {
    setOpen(false);
    onChangeSeverity(insightId, sev, applyToAll);
  }

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className={clsx(
          "rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600 transition-opacity",
          open ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        )}
        title="Actions"
      >
        <MoreHorizontal size={14} />
      </button>

      {open && (
        <div
          className="absolute right-0 top-6 z-50 w-52 rounded-md border border-slate-200 bg-white py-1 shadow-lg text-sm"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={handleIgnoreInstance}
            className="w-full px-3 py-1.5 text-left text-slate-700 hover:bg-slate-50"
          >
            Ignore this instance
          </button>
          <button
            onClick={handleIgnoreRule}
            className="w-full px-3 py-1.5 text-left text-slate-700 hover:bg-slate-50"
          >
            Ignore all <span className="font-mono">{ruleId}</span>
          </button>

          <div className="my-1 border-t border-slate-100" />

          <p className="px-3 py-1 text-xs font-medium text-slate-400 uppercase tracking-wide">
            Change severity to
          </p>
          {SEVERITIES.map((sev) => (
            <button
              key={sev}
              onClick={() => handleSeverity(sev)}
              className={clsx(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50",
                sev === currentSeverity ? "text-indigo-600 font-medium" : "text-slate-700"
              )}
            >
              <span
                className={clsx(
                  "h-1.5 w-1.5 rounded-full",
                  sev === currentSeverity ? "bg-indigo-500" : "bg-transparent border border-slate-300"
                )}
              />
              <span className="capitalize">{sev}</span>
              {sev === currentSeverity && (
                <span className="ml-auto text-xs text-slate-400">current</span>
              )}
            </button>
          ))}

          <div className="my-1 border-t border-slate-100" />

          <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 hover:bg-slate-50">
            <input
              type="checkbox"
              checked={applyToAll}
              onChange={(e) => setApplyToAll(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600"
            />
            <span className="text-slate-600">
              Apply to future <span className="font-mono">{ruleId}</span> firings
            </span>
          </label>
        </div>
      )}
    </div>
  );
}
