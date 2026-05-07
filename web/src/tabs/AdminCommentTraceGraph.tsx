// R5-B + R7-B: Comment Trace Graph (Obsidian-like force-directed view).
// Read-only. cytoscape 시각화. 두 graph mode 지원:
//   - "provenance": graph_seed (R4 — section/evidence 구조)
//   - "causal":     graph_seed_causal (R7 — evidence/claim/event/macro/asset/path)
// 데이터 생성 로직은 변경하지 않음.
import { useMemo, useRef, useState, type CSSProperties } from "react";
import CytoscapeComponent from "react-cytoscapejs";
import type { Core, ElementDefinition } from "cytoscape";

// ──────────────────────────────────────────────────────────────────
// Types — graph_seed payload
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
type GraphMode = "provenance" | "causal";

// ──────────────────────────────────────────────────────────────────
// Provenance schema (R4)
// ──────────────────────────────────────────────────────────────────
const PROV_NODE_TYPES = [
  "comment", "comment_section", "market_source", "evidence",
  "wiki_page", "asset_class", "fund", "metric", "warning",
] as const;
type ProvNodeType = (typeof PROV_NODE_TYPES)[number];

const PROV_EDGE_TYPES = [
  "comment_has_section", "section_uses_market_source",
  "section_uses_evidence", "section_uses_wiki",
  "section_mentions_asset", "section_uses_metric",
  "fund_has_metric", "warning_applies_to_section",
] as const;
type ProvEdgeType = (typeof PROV_EDGE_TYPES)[number];

const PROV_NODE_STYLE: Record<ProvNodeType, { color: string; shape: string; size: number }> = {
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

const PROV_EDGE_COLOR: Record<ProvEdgeType, string> = {
  comment_has_section:        "#1f2937",
  section_uses_market_source: "#0d9488",
  section_uses_evidence:      "#10b981",
  section_uses_wiki:          "#8b5cf6",
  section_mentions_asset:     "#f59e0b",
  section_uses_metric:        "#64748b",
  fund_has_metric:            "#475569",
  warning_applies_to_section: "#dc2626",
};

const PROV_EDGE_DEFAULT: Record<ProvEdgeType, boolean> = {
  comment_has_section: true,
  section_uses_market_source: true,
  section_uses_evidence: false, // 기본 off — clutter 방지
  section_uses_wiki: true,
  section_mentions_asset: true,
  section_uses_metric: true,
  fund_has_metric: true,
  warning_applies_to_section: true,
};

// ──────────────────────────────────────────────────────────────────
// Causal schema (R7)
// ──────────────────────────────────────────────────────────────────
const CAUSAL_NODE_TYPES = [
  "claim", "evidence", "event", "macro_factor",
  "asset_class", "fund", "path", "comment_section",
] as const;
type CausalNodeType = (typeof CAUSAL_NODE_TYPES)[number];

const CAUSAL_EDGE_TYPES = [
  "evidence_supports_claim",
  "claim_mentions_event",
  "claim_mentions_macro",
  "claim_mentions_asset",
  "event_raises_macro",
  "event_lowers_macro",
  "macro_pressures_asset",
  "macro_supports_asset",
  "asset_affects_fund",
  "path_includes_node",
  "path_supported_by_evidence",
  "section_uses_causal_path",
] as const;
type CausalEdgeType = (typeof CAUSAL_EDGE_TYPES)[number];

// path 가 가장 눈에 띄게. claim 은 작게. event/macro/asset/fund 는 색으로 구분.
const CAUSAL_NODE_STYLE: Record<CausalNodeType, { color: string; shape: string; size: number }> = {
  claim:           { color: "#475569", shape: "round-rectangle", size: 28 },
  evidence:        { color: "#10b981", shape: "ellipse",         size: 22 },
  event:           { color: "#ef4444", shape: "octagon",         size: 50 },
  macro_factor:    { color: "#f59e0b", shape: "round-rectangle", size: 44 },
  asset_class:     { color: "#3b82f6", shape: "round-rectangle", size: 44 },
  fund:            { color: "#111827", shape: "round-rectangle", size: 60 },
  path:            { color: "#a855f7", shape: "round-diamond",   size: 70 },
  comment_section: { color: "#2563eb", shape: "round-rectangle", size: 36 },
};

const CAUSAL_EDGE_COLOR: Record<CausalEdgeType, string> = {
  evidence_supports_claim:    "#10b981",
  claim_mentions_event:       "#ef4444",
  claim_mentions_macro:       "#f59e0b",
  claim_mentions_asset:       "#3b82f6",
  event_raises_macro:         "#dc2626",
  event_lowers_macro:         "#0891b2",
  macro_pressures_asset:      "#b45309",
  macro_supports_asset:       "#15803d",
  asset_affects_fund:         "#1e293b",
  path_includes_node:         "#a855f7",
  path_supported_by_evidence: "#7c3aed",
  section_uses_causal_path:   "#2563eb",
};

const CAUSAL_EDGE_DEFAULT: Record<CausalEdgeType, boolean> = {
  evidence_supports_claim:    false, // 기본 off — clutter 방지 (15+ 개)
  claim_mentions_event:       true,
  claim_mentions_macro:       true,
  claim_mentions_asset:       true,
  event_raises_macro:         true,
  event_lowers_macro:         true,
  macro_pressures_asset:      true,
  macro_supports_asset:       true,
  asset_affects_fund:         true,
  path_includes_node:         true,
  path_supported_by_evidence: false, // 기본 off — path-evidence fanout
  section_uses_causal_path:   true,
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
const TOGGLE_BTN_BASE: CSSProperties = {
  padding: "4px 12px", fontSize: 11, fontFamily: "ui-monospace, monospace",
  cursor: "pointer", border: "1px solid #94a3b8", background: "#fff",
};
const TOGGLE_BTN_ACTIVE: CSSProperties = {
  ...TOGGLE_BTN_BASE, background: "#1e293b", color: "#fff",
  borderColor: "#1e293b",
};

// ──────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────
export default function AdminCommentTraceGraph({
  provenance,
  causal,
}: {
  provenance: GraphSeed | undefined | null;
  causal?: GraphSeed | undefined | null;
}) {
  const [show, setShow] = useState(false);
  const [mode, setMode] = useState<GraphMode>("provenance");

  // mode 별 filter state (둘 다 유지하면 토글 시 마지막 상태 보존)
  const [provNodeFilter, setProvNodeFilter] = useState<Record<ProvNodeType, boolean>>(
    () => Object.fromEntries(PROV_NODE_TYPES.map((t) => [t, true])) as Record<ProvNodeType, boolean>,
  );
  const [provEdgeFilter, setProvEdgeFilter] = useState<Record<ProvEdgeType, boolean>>(
    () => ({ ...PROV_EDGE_DEFAULT }),
  );
  const [causalNodeFilter, setCausalNodeFilter] = useState<Record<CausalNodeType, boolean>>(
    () => Object.fromEntries(CAUSAL_NODE_TYPES.map((t) => [t, true])) as Record<CausalNodeType, boolean>,
  );
  const [causalEdgeFilter, setCausalEdgeFilter] = useState<Record<CausalEdgeType, boolean>>(
    () => ({ ...CAUSAL_EDGE_DEFAULT }),
  );

  const [selected, setSelected] = useState<{
    kind: "node" | "edge"; data: Record<string, unknown>;
  } | null>(null);

  const cyRef = useRef<Core | null>(null);

  // 현 mode 의 graph / types / style maps
  const graph: GraphSeed | null | undefined = mode === "causal" ? causal : provenance;
  const nodes = (graph?.nodes ?? []) as GNode[];
  const edges = (graph?.edges ?? []) as GEdge[];

  const NODE_TYPES_CUR: readonly string[] =
    mode === "causal" ? CAUSAL_NODE_TYPES : PROV_NODE_TYPES;
  const EDGE_TYPES_CUR: readonly string[] =
    mode === "causal" ? CAUSAL_EDGE_TYPES : PROV_EDGE_TYPES;

  const nodeFilterCur: Record<string, boolean> =
    mode === "causal" ? causalNodeFilter : provNodeFilter;
  const edgeFilterCur: Record<string, boolean> =
    mode === "causal" ? causalEdgeFilter : provEdgeFilter;

  const onNodeFilterChange = (t: string, v: boolean) => {
    if (mode === "causal") {
      setCausalNodeFilter((f) => ({ ...f, [t as CausalNodeType]: v }));
    } else {
      setProvNodeFilter((f) => ({ ...f, [t as ProvNodeType]: v }));
    }
  };
  const onEdgeFilterChange = (t: string, v: boolean) => {
    if (mode === "causal") {
      setCausalEdgeFilter((f) => ({ ...f, [t as CausalEdgeType]: v }));
    } else {
      setProvEdgeFilter((f) => ({ ...f, [t as ProvEdgeType]: v }));
    }
  };

  const nodeColor = (t: string): string =>
    mode === "causal"
      ? CAUSAL_NODE_STYLE[t as CausalNodeType]?.color ?? "#9ca3af"
      : PROV_NODE_STYLE[t as ProvNodeType]?.color ?? "#9ca3af";
  const edgeColor = (t: string): string =>
    mode === "causal"
      ? CAUSAL_EDGE_COLOR[t as CausalEdgeType] ?? "#94a3b8"
      : PROV_EDGE_COLOR[t as ProvEdgeType] ?? "#94a3b8";

  const visibleNodeIds = useMemo(() => {
    const set = new Set<string>();
    for (const n of nodes) {
      const t = n.type;
      if (NODE_TYPES_CUR.includes(t)) {
        if (nodeFilterCur[t]) set.add(n.id);
      } else {
        set.add(n.id); // unknown type → 표시
      }
    }
    return set;
  }, [nodes, NODE_TYPES_CUR, nodeFilterCur]);

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
      const t = e.type;
      if (EDGE_TYPES_CUR.includes(t) && !edgeFilterCur[t]) continue;
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
  }, [nodes, edges, visibleNodeIds, EDGE_TYPES_CUR, edgeFilterCur]);

  const visibleNodeCount = elements.filter(
    (el: ElementDefinition) => !el.data.source,
  ).length;
  const visibleEdgeCount = elements.length - visibleNodeCount;

  // 상단 summary용 — total counts (filter 무관)
  const counts = useMemo(() => {
    const c: Record<string, number> = {
      total_nodes: nodes.length, total_edges: edges.length,
      claim: 0, evidence: 0, path: 0, fund: 0, comment_section: 0,
    };
    for (const n of nodes) {
      if (n.type in c) c[n.type] = (c[n.type] ?? 0) + 1;
    }
    return c;
  }, [nodes, edges]);

  const stylesheet = useMemo(() => {
    const sty: unknown[] = [
      {
        selector: "node",
        style: {
          label: "data(label)", "font-size": 9,
          "text-valign": "center", "text-halign": "center",
          color: "#fff", "text-outline-color": "#1f2937",
          "text-outline-width": 1, "text-wrap": "wrap",
          "text-max-width": 80, width: 30, height: 30,
          "background-color": "#9ca3af",
        },
      },
      {
        selector: "edge",
        style: {
          width: 1.5, "line-color": "#94a3b8",
          "target-arrow-color": "#94a3b8",
          "target-arrow-shape": "triangle",
          "curve-style": "bezier", "arrow-scale": 0.6,
          opacity: 0.7,
        },
      },
      {
        selector: "node:selected",
        style: { "border-width": 3, "border-color": "#facc15" },
      },
      {
        selector: "edge:selected",
        style: {
          width: 3, "line-color": "#facc15",
          "target-arrow-color": "#facc15", opacity: 1,
        },
      },
    ];
    if (mode === "causal") {
      for (const t of CAUSAL_NODE_TYPES) {
        const s = CAUSAL_NODE_STYLE[t];
        sty.push({
          selector: `node[ntype="${t}"]`,
          style: {
            shape: s.shape, width: s.size, height: s.size,
            "background-color": s.color,
          },
        });
      }
      for (const t of CAUSAL_EDGE_TYPES) {
        sty.push({
          selector: `edge[etype="${t}"]`,
          style: {
            "line-color": CAUSAL_EDGE_COLOR[t],
            "target-arrow-color": CAUSAL_EDGE_COLOR[t],
            // path edge 강조, evidence_supports_claim 흐리게
            width: t === "path_includes_node" || t === "path_supported_by_evidence" ? 2.5 : 1.5,
            "line-style": t === "section_uses_causal_path" ? "dashed" : "solid",
            opacity: t === "evidence_supports_claim" ? 0.4 : 0.85,
          },
        });
      }
    } else {
      for (const t of PROV_NODE_TYPES) {
        const s = PROV_NODE_STYLE[t];
        sty.push({
          selector: `node[ntype="${t}"]`,
          style: {
            shape: s.shape, width: s.size, height: s.size,
            "background-color": s.color,
          },
        });
      }
      for (const t of PROV_EDGE_TYPES) {
        sty.push({
          selector: `edge[etype="${t}"]`,
          style: {
            "line-color": PROV_EDGE_COLOR[t],
            "target-arrow-color": PROV_EDGE_COLOR[t],
            opacity: t === "section_uses_evidence" ? 0.45 : 0.8,
          },
        });
      }
    }
    return sty;
  }, [mode]);

  const layout = useMemo(
    () => ({
      name: "cose", idealEdgeLength: 110, nodeRepulsion: 9000,
      animate: false, randomize: true, componentSpacing: 50,
      padding: 30, fit: true,
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

  // mode 바뀌면 selection / cy 재초기화 — selection 은 reset
  const onModeChange = (m: GraphMode) => {
    if (m === mode) return;
    setMode(m);
    setSelected(null);
  };

  const noGraph = !graph;
  const noNodes = (nodes?.length ?? 0) === 0;
  const noEdges = (edges?.length ?? 0) === 0;
  const causalAvailable = !!causal && (causal.nodes?.length ?? 0) > 0;

  return (
    <div style={CARD}>
      <div style={{
        display: "flex", justifyContent: "space-between",
        alignItems: "center", marginBottom: 8, flexWrap: "wrap", gap: 8,
      }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          Graph View · mode={mode}
          {show && ` · nodes ${visibleNodeCount} / edges ${visibleEdgeCount}`}
        </div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {/* Mode toggle */}
          <button
            onClick={() => onModeChange("provenance")}
            style={mode === "provenance" ? TOGGLE_BTN_ACTIVE : TOGGLE_BTN_BASE}
          >
            Provenance
          </button>
          <button
            onClick={() => onModeChange("causal")}
            disabled={!causalAvailable}
            title={causalAvailable ? "Causal graph (R7)" : "graph_seed_causal 없음"}
            style={mode === "causal" ? TOGGLE_BTN_ACTIVE : TOGGLE_BTN_BASE}
          >
            Causal
          </button>
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

      {/* Causal summary header (R7-B 요구) */}
      {show && mode === "causal" && !noGraph && (
        <div style={{
          fontSize: 11, fontFamily: "ui-monospace, monospace",
          color: "#475569", marginBottom: 8, padding: "6px 8px",
          background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 4,
        }}>
          <strong>causal</strong> · nodes {counts.total_nodes} / edges {counts.total_edges}
          {" · "}claims {counts.claim} · evidence {counts.evidence}
          {" · "}path {counts.path} · sections {counts.comment_section}
        </div>
      )}

      {show && noGraph && (
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          {mode === "causal" ? "graph_seed_causal 없음." : "graph_seed 없음."}
        </div>
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
              {NODE_TYPES_CUR.map((t) => (
                <label key={t} style={CHECKBOX_LABEL}>
                  <input
                    type="checkbox"
                    checked={nodeFilterCur[t] ?? true}
                    onChange={(e) => onNodeFilterChange(t, e.target.checked)}
                  />
                  <span style={COLOR_DOT(nodeColor(t))} />
                  {t}
                </label>
              ))}
            </div>
            <div>
              <span style={{ fontSize: 11, fontWeight: 600, marginRight: 8 }}>Edges:</span>
              {EDGE_TYPES_CUR.map((t) => (
                <label key={t} style={CHECKBOX_LABEL}>
                  <input
                    type="checkbox"
                    checked={edgeFilterCur[t] ?? true}
                    onChange={(e) => onEdgeFilterChange(t, e.target.checked)}
                  />
                  <span style={COLOR_DOT(edgeColor(t))} />
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
                key={`${mode}-${nodes.length}-${edges.length}`}
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
  const isPath = data?.type === "path";
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
          {isPath && <PathDetail data={data} />}
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

// path 노드 클릭 시 chain / supporting evidence / linked sections 별도 표시.
// graph_seed_causal.nodes 의 path entry 는 confidence/label/chain 정보가
// raw 에 직접 들어있지 않을 수 있어 (그래프에는 label 만 들어옴), raw 에 있는
// 정보만 표시하고 path detail 은 trace.causal_paths 에 fall-back.
function PathDetail({ data }: { data: Record<string, unknown> }) {
  const conf = data?.confidence;
  return (
    <div style={{
      marginTop: 6, padding: 6, background: "#f3e8ff",
      color: "#6b21a8", borderRadius: 3,
    }}>
      <div><strong>causal path</strong></div>
      {conf !== undefined && (
        <div>confidence: {String(conf)}</div>
      )}
      <div style={{ marginTop: 4, fontSize: 10, color: "#581c87" }}>
        path 의 chain / supporting_evidence_ids / linked_sections 는
        Trace 본문 패널의 <code>causal_paths</code> 에서 확인.
      </div>
    </div>
  );
}
