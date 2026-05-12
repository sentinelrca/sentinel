"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { deleteSource } from "@/lib/api";
import SourceForm from "./source-form";
import type { Source } from "@/lib/types";
import { formatDistanceToNow } from "@/lib/date";

const KIND_LABELS: Record<string, string> = {
  langfuse: "Langfuse",
  langsmith: "LangSmith",
};

interface Props {
  initialItems: Source[];
}

export default function SourceList({ initialItems }: Props) {
  const [items, setItems] = useState<Source[]>(initialItems);
  const [showForm, setShowForm] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function handleDelete(id: string) {
    if (!confirm("Remove this source?")) return;
    setDeleting(id);
    try {
      await deleteSource(id);
      setItems((prev) => prev.filter((s) => s.id !== id));
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setDeleting(null);
    }
  }

  function handleCreated(source: Source) {
    setItems((prev) => [source, ...prev]);
    setShowForm(false);
  }

  return (
    <div>
      <div className="mb-4 flex justify-end">
        <button
          onClick={() => setShowForm(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          <Plus size={14} /> Add source
        </button>
      </div>

      {items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 py-16 text-center text-sm text-slate-400">
          No sources connected yet
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between rounded-lg border border-slate-200 bg-white px-4 py-3"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-900">
                    {KIND_LABELS[s.kind] ?? s.kind}
                  </span>
                  {s.alias && (
                    <span className="text-xs text-slate-500">{s.alias}</span>
                  )}
                </div>
                <p className="text-xs text-slate-400">
                  {s.created_at ? `Added ${formatDistanceToNow(s.created_at)}` : ""}
                </p>
              </div>
              <button
                onClick={() => handleDelete(s.id)}
                disabled={deleting === s.id}
                className="rounded p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-500 disabled:opacity-40"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <SourceForm onCreated={handleCreated} onCancel={() => setShowForm(false)} />
      )}
    </div>
  );
}
