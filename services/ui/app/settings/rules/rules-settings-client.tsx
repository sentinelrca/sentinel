"use client";

import { useState } from "react";
import { putRuleConfig, deleteRuleConfig } from "@/lib/api";
import { clsx } from "clsx";

const SEVERITIES = ["critical", "high", "warning", "info"] as const;

interface RuleEntry {
  detector_id: string;
  name: string;
  default_severity: string;
  description: string;
}

interface ConfigState {
  action: string;
  severity: string | null;
}

interface Props {
  rules: RuleEntry[];
  initialConfigs: Record<string, ConfigState>;
}

export default function RulesSettingsClient({ rules, initialConfigs }: Props) {
  const [configs, setConfigs] = useState<Record<string, ConfigState>>(initialConfigs);
  const [saving, setSaving] = useState<string | null>(null);

  function getEffectiveSeverity(rule: RuleEntry): string {
    const cfg = configs[rule.detector_id];
    if (cfg?.action === "OVERRIDE_SEVERITY" && cfg.severity) return cfg.severity;
    return rule.default_severity;
  }

  function isDisabled(detector_id: string) {
    return configs[detector_id]?.action === "DISABLED";
  }

  function isModified(rule: RuleEntry) {
    return !!configs[rule.detector_id];
  }

  async function handleToggleDisabled(rule: RuleEntry) {
    setSaving(rule.detector_id);
    try {
      if (isDisabled(rule.detector_id)) {
        await deleteRuleConfig(rule.detector_id);
        setConfigs((prev) => { const n = { ...prev }; delete n[rule.detector_id]; return n; });
      } else {
        await putRuleConfig(rule.detector_id, { action: "DISABLED" });
        setConfigs((prev) => ({ ...prev, [rule.detector_id]: { action: "DISABLED", severity: null } }));
      }
    } finally {
      setSaving(null);
    }
  }

  async function handleSeverityChange(rule: RuleEntry, severity: string) {
    setSaving(rule.detector_id);
    try {
      await putRuleConfig(rule.detector_id, { action: "OVERRIDE_SEVERITY", severity });
      setConfigs((prev) => ({ ...prev, [rule.detector_id]: { action: "OVERRIDE_SEVERITY", severity } }));
    } finally {
      setSaving(null);
    }
  }

  async function handleReset(rule: RuleEntry) {
    setSaving(rule.detector_id);
    try {
      await deleteRuleConfig(rule.detector_id);
      setConfigs((prev) => { const n = { ...prev }; delete n[rule.detector_id]; return n; });
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
      {rules.map((rule) => {
        const disabled = isDisabled(rule.detector_id);
        const modified = isModified(rule);
        const effectiveSev = getEffectiveSeverity(rule);
        const isSaving = saving === rule.detector_id;

        return (
          <div
            key={rule.detector_id}
            className={clsx("flex items-start gap-4 px-5 py-4", disabled && "opacity-50")}
          >
            {/* Info */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-800">{rule.name}</span>
                <span className="font-mono text-xs text-slate-400">{rule.detector_id}</span>
                {disabled && (
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                    MUTED
                  </span>
                )}
                {modified && !disabled && (
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-600">
                    modified
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-sm text-slate-500">{rule.description}</p>
              <p className="mt-1 text-xs text-slate-400">
                Built-in severity:{" "}
                <span className="font-medium capitalize">{rule.default_severity}</span>
              </p>
            </div>

            {/* Severity selector */}
            <div className="flex items-center gap-2">
              <select
                value={effectiveSev}
                onChange={(e) => handleSeverityChange(rule, e.target.value)}
                disabled={disabled || isSaving}
                className="rounded-md border border-slate-200 px-2 py-1 text-sm text-slate-700 disabled:opacity-40"
              >
                {SEVERITIES.map((s) => (
                  <option key={s} value={s} className="capitalize">
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>

              {modified && (
                <button
                  onClick={() => handleReset(rule)}
                  disabled={isSaving}
                  className="text-xs text-slate-400 hover:text-slate-600 disabled:opacity-40"
                  title="Reset to default"
                >
                  Reset
                </button>
              )}

              {/* Mute toggle */}
              <button
                onClick={() => handleToggleDisabled(rule)}
                disabled={isSaving}
                className={clsx(
                  "rounded-md border px-3 py-1 text-xs font-medium transition-colors disabled:opacity-40",
                  disabled
                    ? "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                    : "border-red-200 bg-red-50 text-red-600 hover:bg-red-100"
                )}
              >
                {disabled ? "Re-enable" : "Mute"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
