export type Severity = "critical" | "high" | "warning" | "info";

export interface Insight {
  id: string;
  trace_id: string;
  rule_id: string;
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
  rule_ids: string[];
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
