"use client";

import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { FlowNode, FlowEdge, Insight } from "@/lib/types";

const KIND_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  llm_call:     { bg: "#ede9fe", border: "#7c3aed", text: "#4c1d95" },
  tool_invoke:  { bg: "#dbeafe", border: "#2563eb", text: "#1e3a8a" },
  chain:        { bg: "#f1f5f9", border: "#64748b", text: "#1e293b" },
  retrieval:    { bg: "#dcfce7", border: "#16a34a", text: "#14532d" },
  agent_invoke: { bg: "#fef9c3", border: "#ca8a04", text: "#713f12" },
};

function buildLayout(nodes: FlowNode[]): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const children = new Map<string, string[]>();
  const roots: string[] = [];

  for (const n of nodes) {
    if (!n.parent_id || !nodes.find((x) => x.id === n.parent_id)) {
      roots.push(n.id);
    } else {
      const list = children.get(n.parent_id) ?? [];
      list.push(n.id);
      children.set(n.parent_id, list);
    }
  }

  let yCounter = 0;
  function place(id: string, depth: number) {
    positions.set(id, { x: depth * 200, y: yCounter * 90 });
    yCounter++;
    for (const child of children.get(id) ?? []) place(child, depth + 1);
  }
  for (const root of roots) place(root, 0);
  return positions;
}

interface Props {
  nodes: FlowNode[];
  edges: FlowEdge[];
  affectedSpanIds: string[];
  allInsights?: Insight[];
  selectedSpanId?: string | null;
  onNodeClick?: (span: FlowNode) => void;
}

export default function FlowGraphCanvas({
  nodes,
  edges,
  affectedSpanIds,
  allInsights = [],
  selectedSpanId,
  onNodeClick,
}: Props) {
  const affectedSet = useMemo(() => new Set(affectedSpanIds), [affectedSpanIds]);
  const positions = useMemo(() => buildLayout(nodes), [nodes]);

  // Worst severity per span across all insights that flag it (for dot color)
  const spanSeverity = useMemo(() => {
    const order: Record<string, number> = { critical: 4, high: 3, warning: 2, info: 1 };
    const map = new Map<string, string>();
    for (const ins of allInsights) {
      for (const sid of ins.affected_span_ids) {
        const cur = map.get(sid);
        if (!cur || (order[ins.severity] ?? 0) > (order[cur] ?? 0)) {
          map.set(sid, ins.severity);
        }
      }
    }
    return map;
  }, [allInsights]);

  const rfNodes: Node[] = useMemo(
    () =>
      nodes.map((n) => {
        const colors = KIND_COLORS[n.kind] ?? KIND_COLORS.chain;
        const isAffected = affectedSet.has(n.id);
        const isSelected = selectedSpanId === n.id;
        const dotSeverity = spanSeverity.get(n.id);

        let border = `1px solid ${colors.border}`;
        let boxShadow: string | undefined;
        if (isSelected) {
          border = "2px solid #2563eb";
          boxShadow = "0 0 0 2px #bfdbfe";
        } else if (isAffected) {
          border = "2px solid #dc2626";
          boxShadow = "0 0 0 2px #fca5a5";
        }

        return {
          id: n.id,
          position: positions.get(n.id) ?? { x: 0, y: 0 },
          data: { label: <NodeLabel node={n} dotSeverity={dotSeverity} /> },
          style: {
            background: colors.bg,
            border,
            boxShadow,
            color: colors.text,
            borderRadius: 8,
            padding: "6px 10px",
            fontSize: 11,
            width: 180,
            cursor: onNodeClick ? "pointer" : "default",
          },
        };
      }),
    [nodes, positions, affectedSet, selectedSpanId, spanSeverity, onNodeClick]
  );

  const rfEdges: Edge[] = useMemo(
    () =>
      edges.map((e, i) => ({
        id: `e${i}`,
        source: e.source,
        target: e.target,
        type: "smoothstep",
        animated: e.kind === "loop_back",
        style: { stroke: "#94a3b8", strokeWidth: 1.5 },
      })),
    [edges]
  );

  const handleNodeClick: NodeMouseHandler = useCallback(
    (_event, rfNode) => {
      const span = nodes.find((n) => n.id === rfNode.id);
      if (span) onNodeClick?.(span);
    },
    [nodes, onNodeClick]
  );

  return (
    <div style={{ height: Math.max(400, nodes.length * 90 + 80) }}>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        fitView
        onNodeClick={onNodeClick ? handleNodeClick : undefined}
      >
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}

function NodeLabel({ node, dotSeverity }: { node: FlowNode; dotSeverity?: string }) {
  const dotColor =
    dotSeverity === "critical" || dotSeverity === "high"
      ? "bg-red-500"
      : dotSeverity
      ? "bg-amber-400"
      : null;

  return (
    <div className="relative leading-tight">
      {dotColor && (
        <span
          className={`absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full ${dotColor} ring-1 ring-white`}
          title={dotSeverity}
        />
      )}
      <div className="truncate font-medium" style={{ maxWidth: 156 }}>
        {node.name || node.id.slice(0, 8)}
      </div>
      <div className="mt-0.5 flex gap-2 text-[10px] opacity-70">
        <span>{node.kind}</span>
        {node.duration_ms > 0 && <span>{node.duration_ms}ms</span>}
        {node.status === "error" && <span className="text-red-600">error</span>}
      </div>
      {((node.input_tokens ?? 0) > 0 || (node.output_tokens ?? 0) > 0) && (
        <div className="mt-0.5 text-[10px] opacity-60">
          {node.input_tokens ?? 0}↑ {node.output_tokens ?? 0}↓
        </div>
      )}
    </div>
  );
}
