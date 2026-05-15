import type {
  FlowGraph,
  Insight,
  InsightListResponse,
  Source,
  SourceListResponse,
  TraceInsightsResponse,
  TraceListResponse,
} from "./types";

const BASE_URL = process.env.SENTINEL_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.SENTINEL_API_KEY ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${API_KEY}`,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export interface InsightFilters {
  limit?: number;
  offset?: number;
  severity?: string;
  rule_id?: string;
  trace_id?: string;
  from_time?: string;
  to_time?: string;
}

export async function getInsights(filters: InsightFilters = {}): Promise<InsightListResponse> {
  const params = new URLSearchParams();
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.rule_id) params.set("rule_id", filters.rule_id);
  if (filters.trace_id) params.set("trace_id", filters.trace_id);
  if (filters.from_time) params.set("from_time", filters.from_time);
  if (filters.to_time) params.set("to_time", filters.to_time);
  const qs = params.toString();
  return apiFetch<InsightListResponse>(`/v1/insights${qs ? `?${qs}` : ""}`);
}

export async function getInsight(id: string): Promise<Insight> {
  return apiFetch<Insight>(`/v1/insights/${id}`);
}

export async function getFlow(traceId: string): Promise<FlowGraph> {
  return apiFetch<FlowGraph>(`/v1/flows/${traceId}`);
}

export interface TraceFilters {
  limit?: number;
  offset?: number;
}

export async function getTraces(filters: TraceFilters = {}): Promise<TraceListResponse> {
  const params = new URLSearchParams();
  if (filters.limit !== undefined) params.set("limit", String(filters.limit));
  if (filters.offset !== undefined) params.set("offset", String(filters.offset));
  const qs = params.toString();
  return apiFetch<TraceListResponse>(`/v1/traces${qs ? `?${qs}` : ""}`);
}

export async function getTraceInsights(traceId: string): Promise<TraceInsightsResponse> {
  return apiFetch<TraceInsightsResponse>(`/v1/traces/${traceId}/insights`);
}

export async function getSources(): Promise<SourceListResponse> {
  return apiFetch<SourceListResponse>("/v1/sources");
}

export async function createSource(body: {
  kind: string;
  alias?: string;
  config_json: Record<string, unknown>;
}): Promise<Source> {
  return apiFetch<Source>("/v1/sources", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function deleteSource(id: string): Promise<void> {
  await apiFetch<unknown>(`/v1/sources/${id}`, { method: "DELETE" });
}
