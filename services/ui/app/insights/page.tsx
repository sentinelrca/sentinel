import { getInsights } from "@/lib/api";
import InsightFeed from "@/components/insight-feed";

interface Props {
  searchParams: { severity?: string; detector_id?: string; page?: string };
}

export default async function InsightsPage({ searchParams }: Props) {
  const page = Number(searchParams.page ?? "1");
  const limit = 50;
  const offset = (page - 1) * limit;

  let data;
  let error: string | null = null;
  try {
    data = await getInsights({
      limit,
      offset,
      severity: searchParams.severity,
      detector_id: searchParams.detector_id,
    });
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load insights";
  }

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-slate-900">Insights</h1>
        <p className="mt-1 text-sm text-slate-500">
          Detected issues across your AI agent traces
        </p>
      </div>
      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <InsightFeed
          items={data!.items}
          total={data!.total}
          page={page}
          limit={limit}
          currentSeverity={searchParams.severity}
          currentRuleId={searchParams.detector_id}
        />
      )}
    </div>
  );
}
