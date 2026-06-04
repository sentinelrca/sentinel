import { getRuleConfigs } from "@/lib/api";
import RulesSettingsClient from "./rules-settings-client";

const RULE_CATALOG = [
  { detector_id: "agent_loop",       name: "Agent Loop",                default_severity: "high",    description: "Detects cycles where agents hand off indefinitely without resolving." },
  { detector_id: "sequential_tools", name: "Sequential Tools",          default_severity: "warning", description: "Detects independent tools run sequentially instead of in parallel." },
];

export default async function RulesSettingsPage() {
  let configs: Record<string, { action: string; severity: string | null }> = {};
  try {
    const result = await getRuleConfigs();
    configs = Object.fromEntries(
      result.items.map((c) => [c.detector_id, { action: c.action, severity: c.severity }])
    );
  } catch {
    // page still renders with defaults
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Rule Settings</h1>
        <p className="mt-1 text-sm text-slate-500">
          Configure which rules fire and at what severity for your workspace.
        </p>
      </div>
      <RulesSettingsClient rules={RULE_CATALOG} initialConfigs={configs} />
    </div>
  );
}
