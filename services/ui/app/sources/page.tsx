import { getSources } from "@/lib/api";
import SourceList from "@/components/source-list";

export default async function SourcesPage() {
  let data;
  let error: string | null = null;
  try {
    data = await getSources();
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load sources";
  }

  return (
    <div className="p-6 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Sources</h1>
        <p className="mt-1 text-sm text-slate-500">
          Connect observability platforms to pull trace data
        </p>
      </div>
      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <SourceList initialItems={data!.items} />
      )}
    </div>
  );
}
