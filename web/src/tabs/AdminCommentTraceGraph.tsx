// R5-B: Comment Trace Graph (Obsidian-like force-directed view).
// Read-only. graph_seed 의 nodes/edges 를 cytoscape 로 시각화.
// 데이터 생성 로직은 변경하지 않음 (R5-A 와 동일 graph_seed 사용).
import { useMemo, useRef, useState, type CSSProperties } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import type { Core, ElementDefinition } from "cytoscape";

// ──────────────────────────────────────────────────────────────────
// Types — graph_seed payload (R4 스키마)
// ──────────────────────────────────────────────────────────────────
type GNode = {
  id: string;
  type: string;
  label?: string;
  [k: string]: unknown;
};
type GEdge = {
  from: string;
  to: string;
  type: string;
  [k: string]: unknown;
};
type GraphSeed = { nodes?: GNode[]; edges?: GEdge[] };

const NODE_TYPES = [
  "comment",
  "comment_section",
  "market_source",
  "evidence",
  "wiki_page",
  "asset_class",
  "fund",
  "metric",
  "warning",
] as const;
type NodeType = (typeof NODE_TYPES)[number];

const EDGE_TYPES = [
  "comment_has_section",
  "section_uses_market_source",
  "section_uses_evidence",
  "section_uses_wiki",
  "section_mentions_asset",
  "section_uses_metric",
  "fund_has_metric",
  "warning_applies_to_section",
] as const;
type EdgeType = (typeof EDGE_TYPES)[number];

// 색상 / 모양 — 너무 화려하지 않게.
const NODE_STYLE: Record<NodeType, { color: string; shape: string; size: number }> = {
  comment:         { color: "#1f2937", shape: "round-rectangle", size: 60 },
  comment_section: { color: "#2563eb", shape: "round-rectangle", size: 48 },
  market_source:   { color: "#0d9488", shape: "diamond",         size: 42 },
  evidence:        { color: "#10b981", shape: "ellipse",         size: 22 },
  wiki_page:       { color: "#8b5cf6", shape: "ellipse",         size: 30 },
  asset_class:     { color: "#f59e0b", shape: "round-rectangle", size: 38 },
  fund:            { color: "#111827", shape: "round-rectangle", size: 56 },
  metric:          { color: "#64748b", shape: "ellipse",         size: 26 },
  warning:         { color: "#dc2626", shape: "diamond",         size: 36 },
};

const EDGE_COLOR: Record<EdgeType, string> = {
  comment_has_section:        "#1f2937",
  section_uses_market_source: "#0d9488",
  section_uses_evidence:      "#10b981",
  section_uses_wiki:          "#8b5cf6",
  section_mentions_asset:     "#f59e0b",
  section_uses_metric:        "#64748b",
  fund_has_metric:            "#475569",
  warning_applies_to_section: "#dc2626",
};

// ──────────────────────────────────────────────────────────────────
// Style helpers
// ──────────────────────────────────────────────────────────────────
const CARD: CSSProperties = {
  border: "1px solid #e5e7eb", borderRadius: 6, padding: 12,
  background: "#fafafa", marginBottom: 12,
};
const CHECKBOX_LABEL: CSSProperties = {
  fontSize: 11, marginRight: 12, fontFamily: "ui-monospace, monospace",
  display: "inline-flex", alignItems: "center", gap: 4,
};
const COLOR_DOT = (c: string): CSSProperties => ({
  display: "inline-block", width: 9, height: 9, borderRadius: 9,
  background: c, marginRight: 2,
});

// ──────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────
export default function AdminCommentTraceGraph({
  graph,
}: {
  graph: GraphSeed | undefined | null;
}) {
  const [show, setShow] = useState(false);
  const [nodeFilter, setNodeFilter] = useState<Record<NodeType, boolean>>({
    comment: true,
    comment_section: true,
    market_source: true,
    evidence: true,        // 노드는 보이게, 단 evidence edges 는 default off (clutter 방지)
    wiki_page: true,
    asset_class: true,
    fund: true,
    metric: true,
    warning: true,
  });
  const [edgeFilter, setEdgeFilter] = useState<Record<EdgeType, boolean>>({
    comment_has_section: true,
    section_uses_market_source: true,
    section_uses_evidence: false, // 기본 off — 화면 정돈
    section_uses_wiki: true,
    section_mentions_asset: true,
    section_uses_metric: true,
    fund_has_metric: true,
    warning_applies_to_section: true,
  });
  const [selected, setSelected] = useState<{
    kind: "node" | "edge"; data: Record<string, unknown>;
  } | null>(null);

  const cyRef = useRef<Core | null>(null);

  const nodes = (graph?.nodes ?? []) as GNode[];
  const edges = (graph?.edges ?? []) as GEdge[];

  const visibleNodeIds = useMemo(() => {
    const set = new Set<string>();
    for (const n of nodes) {
      const t = n.type as NodeType;
      if (NODE_TYPES.includes(t) && nodeFilter[t]) set.add(n.id);
      else if (!NODE_TYPES.includes(t)) set.add(n.id); // unknown type → 표시
    }
    return set;
  }, [nodes, nodeFilter]);

  const elements = useMemo<ElementDefinition[]>(() => {
    const els: ElementDefinition[] = [];
    for (const n of nodes) {
      if (!visibleNodeIds.has(n.id)) continue;
      els.push({
        data: {
          id: n.id,
          label: n.label || n.id,
          ntype: n.type,
          raw: n,
        },
      });
    }
    for (const e of edges) {
      const t = e.type as EdgeType;
      const known = EDGE_TYPES.includes(t);
      if (known && !edgeFilter[t]) continue;
      // edge endpoint 가 hidden node 에 걸리면 skip
      if (!visibleNodeIds.has(e.from) || !visibleNodeIds.has(e.to)) continue;
      els.push({
        data: {
          id: `e:${e.from}->${e.to}:${e.type}`,
          source: e.from,
          target: e.to,
          etype: e.type,
          label: e.type,
          raw: e,
        },
      });
    }
    return els;
  }, [nodes, edges, visibleNodeIds, edgeFilter]);

  // node + edge type 별 visible count
  const visibleNodeCount = elements.filter(
    (el: ElementDefinition) => !el.data.source,
  ).length;
  const visibleEdgeCount = elements.length - visibleNodeCount;

  // cytoscape stylesheet — selector 별 색상/모양
  const stylesheet = useMemo(() => {
    const sty: unknown[] = [
      {
        selector: "node",
        style: {
          label: "data(label)",
          "font-size": 9,
          "text-valign": "center",
          "text-halign": "center",
          color: "#fff",
          "text-outline-color": "#1f2937",
          "text-outline-width": 1,
          "text-wrap": "wrap",
          "text-max-width": 80,
          width: 30,
          height: 30,
          "background-color": "#9ca3af",
        },
      },
      {
        selector: "edge",
        style: {
          width: 1.5,
          "line-color": "#94a3b8",
          "target-arrow-color": "#94a3b8",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier",
          "arrow-scale": 0.6,
          opacity: 0.7,
        },
      },
      {
        selector: "node:selected",
        style: {
          "border-width": 3,
          "border-color": "#facc15",
        },
      },
      {
        selector: "edge:selected",
        style: {
          width: 3,
          "line-color": "#facc15",
          "target-arrow-color": "#facc15",
          opacity: 1,
        },
      },
    ];
    for (const t of NODE_TYPES) {
      const s = NODE_STYLE[t];
      sty.push({
        selector: `node[ntype="${t}"]`,
        style: {
          shape: s.shape,
          width: s.size,
          height: s.size,
          "background-color": s.color,
        },
      });
    }
    for (const t of EDGE_TYPES) {
      const c = EDGE_COLOR[t];
      sty.push({
        selector: `edge[etype="${t}"]`,
        style: {
          "line-color": c,
          "target-arrow-color": c,
          // evidence edges 가 켜져있어도 다소 흐리게
          opacity: t === "section_uses_evidence" ? 0.45 : 0.8,
        },
      });
    }
    return sty;
  }, []);

  const layout = useMemo(
    () => ({
      name: "cose",
      idealEdgeLength: 110,
      nodeRepulsion: 9000,
      animate: false,
      randomize: true,
      componentSpacing: 50,
      padding: 30,
      fit: true,
    }),
    [],
  );

  const handleCy = (cy: Core) => {
    cyRef.current = cy;
    cy.removeAllListeners();
    cy.on("tap", "node", (evt) => {
      const data = evt.target.data();
      setSelected({ kind: "node", data: (data?.raw as Record<string, unknown>) ?? data });
    });
    cy.on("tap", "edge", (evt) => {
      const data = evt.target.data();
      setSelected({ kind: "edge", data: (data?.raw as Record<string, unknown>) ?? data });
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelected(null);
    });
  };

  const resetLayout = () => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.layout(layout).run();
    cy.fit(undefined, 30);
  };

  // ──────────────────────────────────────────────────────────────
  // Empty / disabled states
  // ──────────────────────────────────────────────────────────────
  const noGraph = !graph;
  const noNodes = (nodes?.length ?? 0) === 0;
  const noEdges = (edges?.length ?? 0) === 0;

  return (
    <div style={CARD}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 8,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          Graph View {show && `· nodes ${visibleNodeCount} / edges ${visibleEdgeCount}`}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={resetLayout}
            disabled={!show || noNodes}
            style={{ padding: "3px 10px", fontSize: 11, cursor: "pointer" }}
          >
            Reset Layout
          </button>
          <button
            onClick={() => setShow((s) => !s)}
            style={{ padding: "3px 10px", fontSize: 11, cursor: "pointer" }}
          >
            {show ? "Hide" : "Show"} Graph
          </button>
        </div>
      </div>

      {show && noGraph && (
        <div style={{ fontSize: 12, color: "#6b7280" }}>graph_seed 없음.</div>
      )}
      {show && !noGraph && noNodes && (
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          nodes empty — 표시할 graph 가 없습니다.
        </div>
      )}
      {show && !noGraph && !noNodes && (
        <>
          {/* Filter rows */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
            <div>
              <span style={{ fontSize: 11, fontWeight: 600, marginRight: 8 }}>Nodes:</span>
              {NODE_TYPES.map((t) => (
                <label key={t} style={CHECKBOX_LABEL}>
                  <input
                    type="checkbox"
                    checked={nodeFilter[t]}
                    onChange={(e) =>
                      setNodeFilter((f) => ({ ...f, [t]: e.target.checked }))
                    }
                  />
                  <span style={COLOR_DOT(NODE_STYLE[t].color)} />
                  {t}
                </label>
              ))}
            </div>
            <div>
              <span style={{ fontSize: 11, fontWeight: 600, marginRight: 8 }}>Edges:</span>
              {EDGE_TYPES.map((t) => (
                <label key={t} style={CHECKBOX_LABEL}>
                  <input
                    type="checkbox"
                    checked={edgeFilter[t]}
                    onChange={(e) =>
                      setEdgeFilter((f) => ({ ...f, [t]: e.target.checked }))
                    }
                  />
                  <span style={COLOR_DOT(EDGE_COLOR[t])} />
                  {t}
                </label>
              ))}
            </div>
            {noEdges && (
              <div style={{ fontSize: 11, color: "#92400e" }}>
                ⚠ edges empty — 노드만 표시됩니다.
              </div>
            )}
          </div>

          {/* Graph + Detail */}
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: "2 1 0", minWidth: 0 }}>
              <CytoscapeComponent
                key={`${nodes.length}-${edges.length}`}
                elements={elements}
                style={{
                  width: "100%", height: 540, background: "#0f172a",
                  border: "1px solid #1f2937", borderRadius: 4,
                }}
                stylesheet={stylesheet}
                layout={layout}
                cy={handleCy}
                wheelSensitivity={0.2}
                minZoom={0.2}
                maxZoom={3}
              />
            </div>
            <div style={{ flex: "1 1 0", minWidth: 240, maxWidth: 360 }}>
              <div style={{
                border: "1px solid #e5e7eb", borderRadius: 4,
                background: "#fff", padding: 10, height: 540, overflow: "auto",
              }}>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                  Selection
                </div>
                {!selected && (
                  <div style={{ fontSize: 11, color: "#6b7280" }}>
                    노드 또는 엣지를 클릭하면 상세가 표시됩니다.
                    <br />
                    빈 영역 클릭 = 선택 해제.
                  </div>
                )}
                {selected && (
                  <SelectionDetail kind={selected.kind} data={selected.data} />
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────
// Selection detail panel
// ──────────────────────────────────────────────────────────────────
function SelectionDetail({
  kind, data,
}: { kind: "node" | "edge"; data: Record<string, unknown> }) {
  const isWarning = data?.type === "warning";
  const id = (data?.id as string) ?? "";
  const type = (data?.type as string) ?? "";
  const label = (data?.label as string) ?? "";

  return (
    <div style={{ fontSize: 11, fontFamily: "ui-monospace, monospace" }}>
      <div style={{ marginBottom: 4 }}>
        <strong>kind</strong>: {kind}
      </div>
      {kind === "node" ? (
        <>
          <div><strong>id</strong>: {id}</div>
          <div><strong>type</strong>: {type}{isWarning && " ⚠"}</div>
          <div><strong>label</strong>: {label}</div>
          {isWarning && (
            <div style={{
              marginTop: 6, padding: 6, background: "#fee2e2",
              color: "#991b1b", borderRadius: 3,
            }}>
              warning node — 연결된 section 또는 message 를 raw 에서 확인.
            </div>
          )}
        </>
      ) : (
        <>
          <div><strong>edge type</strong>: {(data?.type as string) ?? ""}</div>
          <div><strong>from</strong>: {(data?.from as string) ?? ""}</div>
          <div><strong>to</strong>: {(data?.to as string) ?? ""}</div>
        </>
      )}
      <div style={{ marginTop: 8, fontWeight: 600 }}>raw</div>
      <pre style={{
        background: "#f3f4f6", padding: 6, fontSize: 10,
        overflow: "auto", maxHeight: 300, marginTop: 4,
        whiteSpace: "pre-wrap", wordBreak: "break-all",
      }}>
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );
}
