export type Severity = "critical" | "high" | "warning" | "info";

export interface Insight {
  id: string;
  trace_id: string;
  detector_id: string;
  severity: Severity;
  title: string;
  detail: string;
  recommendation: string;
  affected_span_ids: string[];
  evidence: Record<string, unknown> | null;
  status: string;
  created_at: string | null;
}

export interface InsightListResponse {
  items: Insight[];
  total: number;
  limit: number;
  offset: number;
}

export interface FlowNode {
  id: string;
  name: string;
  kind: string;
  status: string;
  start_time: string;
  duration_ms: number;
  model: string | null;
  agent_name: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  retry_count: number;
  parent_id: string | null;
  error_message: string | null;
  attributes: Record<string, unknown>;
}

export interface FlowEdge {
  source: string;
  target: string;
  kind: string;
}

export interface FlowStats {
  total_ms: number;
  span_count: number;
  llm_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
}

export interface FlowGraph {
  trace_id: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  has_cycle: boolean;
  stats: FlowStats;
}

export interface TraceSummary {
  trace_id: string;
  worst_severity: Severity;
  insight_count: number;
  detector_ids: string[];
  latest_insight_at: string | null;
  span_count: number;
  llm_calls: number;
  total_ms: number;
}

export interface TraceListResponse {
  items: TraceSummary[];
  total: number;
  limit: number;
  offset: number;
  total_traces_analyzed: number;
  issues_by_severity: Record<string, number>;
  last_synced_at: string | null;
}

export interface TraceInsightsResponse {
  trace_id: string;
  items: Insight[];
  total: number;
}

export interface Source {
  id: string;
  kind: string;
  alias: string | null;
  created_at: string | null;
  last_synced_at: string | null;
}

export interface SourceListResponse {
  items: Source[];
}

export interface RuleConfig {
  detector_id: string;
  action: "DISABLED" | "OVERRIDE_SEVERITY";
  severity: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RuleConfigListResponse {
  items: RuleConfig[];
}

export interface ProjectFilters {
  date_from?: string;   // ISO datetime string
  date_to?: string;     // ISO datetime string
  trace_ids?: string[]; // optional list of trace IDs
}

export interface Project {
  id: string;
  workspace_id: string;
  name: string;
  filters: ProjectFilters;
  status: "pending" | "importing" | "analyzing" | "ready" | "error";
  trace_count: number;
  import_count: number;
  created_at: string;
  last_imported_at: string | null;
  last_analyzed_at: string | null;
}

export interface ProjectsResponse {
  items: Project[];
  total: number;
}
