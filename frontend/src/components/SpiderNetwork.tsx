import { useCallback, useMemo, useState } from "react";
import {
  Background,
  BaseEdge,
  EdgeProps,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getBezierPath,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphEdgeData, GraphNodeData } from "../lib/types";

/* ===========================================================================
   SpiderNetwork - Mode B. The spider is the hub; branches are the genuine results.

   Nodes appear only once the crawl has reached the event that produced them
   (payload.reveal_after), so the graph grows exactly like the investigation did.
   ========================================================================= */

interface Props {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
  upToSeq: number;
  revealedFindingIds: Set<string>;
  selectedFindingId: string | null;
  selectedKeywordId: string | null;
  onSelectFinding: (findingId: string) => void;
  onSelectKeyword: (keywordId: string) => void;
  onNodeDragged?: (id: string, x: number, y: number) => void;
  reducedMotion: boolean;
  showEveryBranch?: boolean;
  /** serialized crawl state, rendered as a data attribute so tests can read what the
      reveal filter was actually given */
  revealState?: string;
}

const TYPE_COLOR: Record<string, string> = {
  spider: "var(--accent)",
  document: "var(--text)",
  section: "var(--topic)",
  topic: "var(--topic)",
  keyword: "var(--keyword)",
  fact: "var(--figure)",
  claim: "var(--logic)",
  evidence: "var(--text-faint)",
  writing_issue: "var(--writing)",
  contradiction: "var(--logic)",
  recommendation: "var(--strength)",
  question: "var(--text-mute)",
};

function SpiderHub({ data }: NodeProps) {
  const payload = data as { investigating?: string; scanning?: boolean };
  return (
    <div className={`hub-node${payload.scanning ? " is-scanning" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <svg viewBox="0 0 44 44" className="hub-spider" aria-hidden="true">
        <g stroke="#5d6773" strokeWidth="1.6" strokeLinecap="round" fill="none">
          <path d="M22 15 L11 6" /><path d="M22 15 L33 6" />
          <path d="M17 21 L5 18" /><path d="M27 21 L39 18" />
          <path d="M17 24 L6 32" /><path d="M27 24 L38 32" />
          <path d="M22 29 L14 40" /><path d="M22 29 L30 40" />
        </g>
        <ellipse cx="22" cy="26" rx="7" ry="6" fill="#1d2228" stroke="#4a525c" strokeWidth="1.2" />
        <ellipse cx="22" cy="17" rx="5" ry="4.4" fill="#252b32" stroke="#8b98a5" strokeWidth="1.1" />
        <circle cx="20" cy="16" r="1.4" fill="#dfe7ea" />
        <circle cx="24" cy="16" r="1.4" fill="#dfe7ea" />
      </svg>
      <div className="hub-label">SPIDER AI</div>
      <div className="hub-sub">{payload.investigating ?? "investigating"}</div>
    </div>
  );
}

function WebNode({ data }: NodeProps) {
  const payload = data as {
    label: string;
    type: string;
    meta?: string;
    selected?: boolean;
    severity?: string;
  };
  return (
    <div
      className={`web-node type-${payload.type}${payload.selected ? " is-selected" : ""}${
        payload.severity ? ` sev-${payload.severity}` : ""
      }`}
      style={{ borderColor: payload.selected ? TYPE_COLOR[payload.type] ?? "#34e2f6" : undefined }}
    >
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />
      <span className="dot" style={{ background: TYPE_COLOR[payload.type] ?? "#7fb2ff" }} />
      <span className="label" title={payload.label}>
        {payload.label}
      </span>
      {payload.meta && <span className="meta">{payload.meta}</span>}
    </div>
  );
}

const nodeTypes = { hub: SpiderHub, web: WebNode };

function TypedEdge(props: EdgeProps) {
  const [path] = getBezierPath(props);
  const relation = (props.data as { relation?: string } | undefined)?.relation ?? "";
  const strong = relation === "supports" || relation === "contains";
  const clash = relation === "contradicts";
  return (
    <BaseEdge
      id={props.id}
      path={path}
      style={{
        stroke: clash ? "rgba(122,79,150,0.75)" : strong ? "rgba(31,111,107,0.45)" : "rgba(120,132,145,0.28)",
        strokeWidth: clash ? 1.8 : strong ? 1.5 : 1,
        strokeDasharray: clash ? "5 4" : relation === "suggests" ? "2 4" : undefined,
      }}
    />
  );
}

const edgeTypes = { web: TypedEdge };

/**
 * Branch sectors around the hub. Each node type owns an arc, so the web reads as the
 * spider's own structure - sections overhead, keywords to the right, claims and evidence
 * below, writing issues and contradictions to the left - instead of one uniform ring.
 * Angles are degrees clockwise from the +X axis; radius is in flow units.
 */
const SECTORS: Record<string, { from: number; to: number; radius: number }> = {
  document: { from: -95, to: -85, radius: 190 },
  section: { from: -170, to: -115, radius: 300 },
  topic: { from: -110, to: -55, radius: 330 },
  keyword: { from: -50, to: 40, radius: 370 },
  fact: { from: 45, to: 115, radius: 380 },
  claim: { from: 120, to: 175, radius: 370 },
  evidence: { from: 180, to: 215, radius: 320 },
  writing_issue: { from: 220, to: 272, radius: 350 },
  contradiction: { from: 276, to: 296, radius: 290 },
  question: { from: 300, to: 318, radius: 250 },
  recommendation: { from: 322, to: 350, radius: 215 },
};

/** Approximate node footprint used to keep branches from overlapping. */
const NODE_SPACING = 235;
const RING_GAP = 118;

/** Vertical squash: the workspace is wide, so the web is an ellipse, not a circle. */
const Y_SQUASH = 0.66;
const X_STRETCH = 1.18;

function layout(nodes: GraphNodeData[], selected: { findingId: string | null; keywordId: string | null }): Node[] {
  const hub = nodes.find((n) => n.node_type === "spider");
  const out: Node[] = [];

  if (hub) {
    out.push({
      id: hub.id,
      type: "hub",
      position: { x: 0, y: 0 },
      data: { label: "SPIDER AI", type: "spider", investigating: "the document" },
      draggable: false,
      selectable: false,
    });
  }

  const byType = new Map<string, GraphNodeData[]>();
  nodes
    .filter((node) => node !== hub)
    .forEach((node) => {
      const bucket = byType.get(node.node_type) ?? [];
      bucket.push(node);
      byType.set(node.node_type, bucket);
    });

  byType.forEach((bucket, type) => {
    // Pack each type's arc as a small grid on concentric rings: strongest branches sit
    // nearest the hub, and no two nodes can land on top of each other.
    const sector = SECTORS[type] ?? { from: 0, to: 360, radius: 430 };
    const ordered = [...bucket].sort((a, b) => b.weight - a.weight);
    const midAngle = ((sector.from + sector.to) / 2) * (Math.PI / 180);
    const arcAvailable = ((sector.to - sector.from) * Math.PI) / 180;
    const columns = Math.max(1, Math.min(ordered.length, Math.floor((arcAvailable * sector.radius) / NODE_SPACING) || 1));
    ordered.forEach((node, index) => {
      const row = Math.floor(index / columns);
      const column = index % columns;
      const inThisRow = Math.min(columns, ordered.length - row * columns);
      const radius = sector.radius + row * RING_GAP;
      const angle = midAngle + (column - (inThisRow - 1) / 2) * (NODE_SPACING / radius);
      const selectedFlag =
        (!!node.ref_id && node.ref_id === selected.findingId) || (!!node.ref_id && node.ref_id === selected.keywordId);
      out.push({
        id: node.id,
        type: "web",
        position: {
          x: Math.cos(angle) * radius * X_STRETCH,
          y: Math.sin(angle) * radius * Y_SQUASH - row * 6,
        },
        data: {
          label: node.label,
          type: node.node_type,
          meta: metaFor(node),
          selected: selectedFlag,
          severity: (node.payload as { severity?: string } | undefined)?.severity,
          refId: node.ref_id,
          passageId: node.passage_id,
        },
        draggable: true,
      });
    });
  });

  return out;
}

function metaFor(node: GraphNodeData): string {
  const payload = node.payload as { occurrences?: number; kind?: string; validation?: string } | undefined;
  if (node.node_type === "keyword" && payload?.occurrences != null) return `${payload.occurrences}x`;
  if (payload?.kind) return payload.kind.replace(/_/g, " ");
  return node.node_type;
}

/** Branch types that get capped in focus mode, and how many of each stay visible. */
const FOCUS_CAP = 6;
const ALWAYS_KEEP = new Set(["spider", "document"]);

function NetworkCanvas(props: Props) {
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({});

  const visible = useMemo(
    () =>
      props.nodes.filter((node) => {
        if (node.node_type === "spider") return true;
        const revealAfter = Number((node.payload as { reveal_after?: number } | undefined)?.reveal_after ?? 0);
        if (props.upToSeq >= Number.MAX_SAFE_INTEGER - 1) return true;
        if (revealAfter <= props.upToSeq) return true;
        // findings/keywords revealed by the crawl cursor keep the graph in step
        if (node.ref_id && props.revealedFindingIds.has(node.ref_id)) return true;
        return false;
      }),
    [props.nodes, props.upToSeq, props.revealedFindingIds],
  );

  // A 137-branch web is honest but unreadable, so focus mode keeps the strongest few of
  // each kind. The complete web is one click away and nothing is hidden from the data.
  const shown = useMemo(() => {
    if (props.showEveryBranch) return visible;
    const byType = new Map<string, GraphNodeData[]>();
    visible.forEach((node) => {
      const bucket = byType.get(node.node_type) ?? [];
      bucket.push(node);
      byType.set(node.node_type, bucket);
    });
    const kept: GraphNodeData[] = [];
    byType.forEach((bucket, type) => {
      if (ALWAYS_KEEP.has(type) || bucket.length <= FOCUS_CAP) {
        kept.push(...bucket);
        return;
      }
      kept.push(...[...bucket].sort((a, b) => b.weight - a.weight).slice(0, FOCUS_CAP));
    });
    return kept;
  }, [visible, props.showEveryBranch]);

  const computed = useMemo(() => {
    const laid = layout(shown, { findingId: props.selectedFindingId, keywordId: props.selectedKeywordId });
    return laid.map((node) => (positions[node.id] ? { ...node, position: positions[node.id] } : node));
  }, [shown, props.selectedFindingId, props.selectedKeywordId, positions]);

  const edges: Edge[] = useMemo(() => {
    const ids = new Set(computed.map((n) => n.id));
    return props.edges
      .filter((edge) => ids.has(edge.source_node_id) && ids.has(edge.target_node_id))
      .map((edge) => ({
        id: edge.id,
        source: edge.source_node_id,
        target: edge.target_node_id,
        type: "web",
        label: undefined,
        data: { relation: edge.relation },
        markerEnd: { type: MarkerType.ArrowClosed, color: "rgba(120,132,145,0.5)", width: 11, height: 11 },
        animated: !props.reducedMotion && edge.relation === "contradicts",
      }));
  }, [computed, props.edges, props.reducedMotion]);

  const onNodeDragStop = useCallback((_: unknown, node: Node) => {
    setPositions((previous) => ({ ...previous, [node.id]: node.position }));
    props.onNodeDragged?.(node.id, node.position.x, node.position.y);
  }, [props]);

  const onNodeClick = useCallback(
    (_: unknown, node: Node) => {
      const data = node.data as { refId?: string | null; type?: string; passageId?: string | null };
      if (!data.refId) return;
      const match = props.nodes.find((n) => n.ref_id === data.refId);
      if (!match) return;
      if (match.node_type === "keyword") props.onSelectKeyword(match.ref_id!);
      else props.onSelectFinding(match.ref_id!);
    },
    [props],
  );

  const onNodesChange = useCallback(
    (changes: { type: string; id?: string; position?: { x: number; y: number } }[]) => {
      const next = { ...positions };
      let changed = false;
      changes.forEach((change) => {
        if (change.type === "position" && change.position && change.id) {
          const current = next[change.id];
          // Ignore sub-pixel churn; otherwise the store feeds itself on every frame.
          if (current && Math.abs(current.x - change.position.x) < 0.5 && Math.abs(current.y - change.position.y) < 0.5) return;
          next[change.id] = change.position;
          changed = true;
        }
      });
      if (changed) setPositions(next);
    },
    [positions],
  );

  return (
    <ReactFlow
      nodes={computed}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onNodeDragStop={onNodeDragStop}
      onNodeClick={onNodeClick}
      fitView
      fitViewOptions={{ padding: 0.18, maxZoom: 1.1 }}
      style={{ width: "100%", height: "100%" }}
      minZoom={0.12}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      nodesConnectable={false}
      elementsSelectable
    >
      <Background color="rgba(120,132,145,0.18)" gap={40} size={1} />
    </ReactFlow>
  );
}

export default function SpiderNetwork(props: Props) {
  const [showEveryBranch, setShowEveryBranch] = useState(false);
  return (
    <ReactFlowProvider>
      <div className="network-shell">
        <div className="network-controls">
          <button className="btn sm ghost" onClick={() => setShowEveryBranch((value) => !value)}>
            {showEveryBranch
              ? `Focus on the strongest branches (${FOCUS_CAP} per kind)`
              : `Show every branch`}
          </button>
          <span className="tiny muted">
            {showEveryBranch ? "every validated result is on the web" : `the strongest ${FOCUS_CAP} of each kind`} -
            drag any node to rearrange
          </span>
        </div>
        <NetworkCanvas {...props} showEveryBranch={showEveryBranch} />
        <div className="network-legend">
          {Object.entries(TYPE_COLOR)
            .filter(([type]) => type !== "spider")
            .map(([type, color]) => (
              <span key={type} className="chip">
                <span className="dot" style={{ background: color, width: 8, height: 8, borderRadius: 50, display: "inline-block" }} />
                {type.replace(/_/g, " ")}
              </span>
            ))}
        </div>
      </div>
    </ReactFlowProvider>
  );
}
