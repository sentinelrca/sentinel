import type {
  FlowGraph,
  Insight,
  InsightListResponse,
  Project,
  ProjectFilters,
  ProjectsResponse,
  RuleConfig,
  RuleConfigListResponse,
  Source,
  SourceListResponse,
  TraceSummary,
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

export async function getFlow(traceId: string, projectId?: string): Promise<FlowGraph> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return apiFetch<FlowGraph>(`/v1/flows/${traceId}${qs}`);
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

export async function patchInsight(
  id: string,
  patch: { status?: string; severity?: string },
): Promise<Insight> {
  return apiFetch<Insight>(`/v1/insights/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function getRuleConfigs(): Promise<RuleConfigListResponse> {
  return apiFetch<RuleConfigListResponse>("/v1/rule-configs");
}

export async function putRuleConfig(
  ruleId: string,
  config: { action: string; severity?: string | null },
): Promise<RuleConfig> {
  return apiFetch<RuleConfig>(`/v1/rule-configs/${ruleId}`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function deleteRuleConfig(ruleId: string): Promise<void> {
  await apiFetch<unknown>(`/v1/rule-configs/${ruleId}`, { method: "DELETE" });
}

export async function getProjects(): Promise<Project[]> {
  const data = await apiFetch<ProjectsResponse>("/v1/projects");
  return data.items;
}

export async function getProject(projectId: string): Promise<Project> {
  return apiFetch<Project>(`/v1/projects/${projectId}`);
}

export async function createProject(name: string, filters: ProjectFilters): Promise<Project> {
  return apiFetch<Project>("/v1/projects", {
    method: "POST",
    body: JSON.stringify({ name, filters }),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiFetch<unknown>(`/v1/projects/${projectId}`, { method: "DELETE" });
}

export async function importProject(projectId: string): Promise<{ task_id: string }> {
  return apiFetch<{ task_id: string }>(`/v1/projects/${projectId}/import`, {
    method: "POST",
  });
}

export async function analyzeProject(projectId: string): Promise<{ task_id: string }> {
  return apiFetch<{ task_id: string }>(`/v1/projects/${projectId}/analyze`, {
    method: "POST",
  });
}

export async function getProjectInsights(projectId: string): Promise<InsightListResponse> {
  return apiFetch<InsightListResponse>(`/v1/projects/${projectId}/insights`);
}

export async function getProjectTraces(projectId: string): Promise<{ items: TraceSummary[]; total: number }> {
  return apiFetch<{ items: TraceSummary[]; total: number }>(`/v1/projects/${projectId}/traces`);
}

export async function listProjects(): Promise<ProjectsResponse> {
  return apiFetch<ProjectsResponse>("/v1/projects");
}
