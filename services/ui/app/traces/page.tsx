import { getTraces } from "@/lib/api";
import TraceCard from "@/components/trace-card";
import Link from "next/link";

interface Props {
  searchParams: { page?: string };
}

export default async function TracesPage({ searchParams }: Props) {
  const page  = Number(searchParams.page ?? "1");
  const limit = 50;
  const offset = (page - 1) * limit;

  let data;
  let error: string | null = null;
  try {
    data = await getTraces({ limit, offset });
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load traces";
  }

  const hasPrev = page > 1;
  const hasNext = data ? offset + data.items.length < data.total : false;

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Traces</h1>
        <p className="mt-1 text-sm text-slate-500">
          {data ? `${data.total} traces with detected issues` : "AI agent traces"}
        </p>
      </div>

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : data?.items.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          No traces with issues found. Connect a source and run a sync to get started.
        </div>
      ) : (
        <>
          <div className="space-y-3">
            {data!.items.map((trace) => (
              <TraceCard key={trace.trace_id} trace={trace} />
            ))}
          </div>

          {(hasPrev || hasNext) && (
            <div className="mt-6 flex items-center justify-between text-sm">
              <span className="text-slate-500">
                {offset + 1}–{offset + data!.items.length} of {data!.total}
              </span>
              <div className="flex gap-2">
                {hasPrev && (
                  <Link
                    href={`/traces?page=${page - 1}`}
                    className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-slate-700 hover:bg-slate-50"
                  >
                    Previous
                  </Link>
                )}
                {hasNext && (
                  <Link
                    href={`/traces?page=${page + 1}`}
                    className="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-slate-700 hover:bg-slate-50"
                  >
                    Next
                  </Link>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
