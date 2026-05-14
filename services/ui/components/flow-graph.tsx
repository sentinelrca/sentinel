"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { FlowNode, FlowEdge } from "@/lib/types";

const KIND_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  llm_call:     { bg: "#ede9fe", border: "#7c3aed", text: "#4c1d95" },
  tool_invoke:  { bg: "#dbeafe", border: "#2563eb", text: "#1e3a8a" },
  chain:        { bg: "#f1f5f9", border: "#64748b", text: "#1e293b" },
  retrieval:    { bg: "#dcfce7", border: "#16a34a", text: "#14532d" },
  agent_invoke: { bg: "#fef9c3", border: "#ca8a04", text: "#713f12" },
};

const AFFECTED_STYLE = { border: "2px solid #dc2626", boxShadow: "0 0 0 2px #fca5a5" };

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
  const X_GAP = 200;
  const Y_GAP = 90;

  function place(id: string, depth: number) {
    const x = depth * X_GAP;
    const y = yCounter * Y_GAP;
    positions.set(id, { x, y });
    yCounter++;
    for (const child of children.get(id) ?? []) {
      place(child, depth + 1);
    }
  }

  for (const root of roots) place(root, 0);

  return positions;
}

interface Props {
  nodes: FlowNode[];
  edges: FlowEdge[];
  affectedSpanIds: string[];
}

export default function FlowGraphCanvas({ nodes, edges, affectedSpanIds }: Props) {
  const affectedSet = useMemo(() => new Set(affectedSpanIds), [affectedSpanIds]);
  const positions = useMemo(() => buildLayout(nodes), [nodes]);

  const rfNodes: Node[] = useMemo(
    () =>
      nodes.map((n) => {
        const colors = KIND_COLORS[n.kind] ?? KIND_COLORS.chain;
        const isAffected = affectedSet.has(n.id);
        return {
          id: n.id,
          position: positions.get(n.id) ?? { x: 0, y: 0 },
          data: { label: <NodeLabel node={n} /> },
          style: {
            background: colors.bg,
            border: isAffected ? AFFECTED_STYLE.border : `1px solid ${colors.border}`,
            boxShadow: isAffected ? AFFECTED_STYLE.boxShadow : undefined,
            color: colors.text,
            borderRadius: 8,
            padding: "6px 10px",
            fontSize: 11,
            width: 180,
          },
        };
      }),
    [nodes, positions, affectedSet]
  );

  const nodeIds = useMemo(() => new Set(nodes.map((n) => n.id)), [nodes]);

  const rfEdges: Edge[] = useMemo(
    () =>
      edges
        .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
        .map((e, i) => ({
          id: `e${i}`,
          source: e.source,
          target: e.target,
          type: "smoothstep",
          animated: e.kind === "loop_back",
          style: { stroke: "#94a3b8", strokeWidth: 1.5 },
        })),
    [edges, nodeIds]
  );

  if (nodes.length === 0) {
    return (
      <div className="flex h-24 items-center justify-center text-sm text-slate-400">
        No spans to display
      </div>
    );
  }

  return (
    <div style={{ height: Math.max(400, nodes.length * 90 + 80) }}>
      <ReactFlow nodes={rfNodes} edges={rfEdges} fitView>
        <Background />
        <Controls />
        <MiniMap />
      </ReactFlow>
    </div>
  );
}

function NodeLabel({ node }: { node: FlowNode }) {
  return (
    <div className="leading-tight">
      <div className="truncate font-medium" style={{ maxWidth: 156 }}>
        {node.name || node.id.slice(0, 8)}
      </div>
      <div className="mt-0.5 flex gap-2 text-[10px] opacity-70">
        <span>{node.kind}</span>
        {node.duration_ms > 0 && <span>{node.duration_ms}ms</span>}
        {node.status === "error" && <span className="text-red-600">error</span>}
      </div>
      {(node.input_tokens > 0 || node.output_tokens > 0) && (
        <div className="mt-0.5 text-[10px] opacity-60">
          {node.input_tokens}↑ {node.output_tokens}↓
        </div>
      )}
    </div>
  );
}
