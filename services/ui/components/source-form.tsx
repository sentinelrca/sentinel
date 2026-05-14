"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { createSource } from "@/lib/api";
import type { Source } from "@/lib/types";

interface FieldDef {
  key: string;
  label: string;
  placeholder: string;
  secret?: boolean;
}

const FIELDS: Record<string, FieldDef[]> = {
  langfuse: [
    { key: "host", label: "Host", placeholder: "https://cloud.langfuse.com" },
    { key: "public_key", label: "Public Key", placeholder: "pk-lf-..." },
    { key: "secret_key", label: "Secret Key", placeholder: "sk-lf-...", secret: true },
  ],
  langsmith: [
    { key: "api_key", label: "API Key", placeholder: "lsv2_pt_...", secret: true },
    { key: "project_name", label: "Project (optional)", placeholder: "my-project" },
  ],
};

interface Props {
  onCreated: (source: Source) => void;
  onCancel: () => void;
}

export default function SourceForm({ onCreated, onCancel }: Props) {
  const [kind, setKind] = useState("langfuse");
  const [alias, setAlias] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fields = FIELDS[kind] ?? [];

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const config_json: Record<string, unknown> = {};
      for (const f of fields) {
        if (values[f.key]) config_json[f.key] = values[f.key];
      }
      const source = await createSource({ kind, alias: alias || undefined, config_json });
      setValues({});
      setAlias("");
      onCreated(source);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create source");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold text-slate-900">Add source</h2>
          <button onClick={onCancel} className="text-slate-400 hover:text-slate-600">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          {/* Kind */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">Platform</label>
            <select
              value={kind}
              onChange={(e) => {
                setKind(e.target.value);
                setValues({});
              }}
              className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
            >
              <option value="langfuse">Langfuse</option>
              <option value="langsmith">LangSmith</option>
            </select>
          </div>

          {/* Alias */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-700">
              Alias <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <input
              type="text"
              value={alias}
              onChange={(e) => setAlias(e.target.value)}
              placeholder="My production Langfuse"
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
            />
          </div>

          {/* Connector fields */}
          {fields.map((f) => (
            <div key={f.key}>
              <label className="mb-1 block text-xs font-medium text-slate-700">
                {f.label}
              </label>
              <input
                type={f.secret ? "password" : "text"}
                value={values[f.key] ?? ""}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                placeholder={f.placeholder}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-slate-400"
              />
            </div>
          ))}

          {error && (
            <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-600">{error}</p>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onCancel}
              className="rounded-md border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {loading ? "Testing connection…" : "Add source"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
