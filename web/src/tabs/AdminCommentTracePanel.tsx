// R5-A: Comment Trace Viewer (read-only, no graph viz).
// 우선 table/tree 기반 + JSON preview. graph layout 은 다음 단계.
import { useMemo, useState, type CSSProperties } from "react";
import {
  useCommentTraceList,
  useCommentTraceLatest,
} from "../hooks/useCommentTrace";

type TraceListItem = {
  trace_id: string;
  fund_code: string;
  period: string;
  generated_at?: string | null;
  schema_version?: string | null;
  graph_node_count?: number;
  graph_edge_count?: number;
  warning_count?: number;
  error_count?: number;
};

const ROW: CSSProperties = { padding: "6px 8px", borderBottom: "1px solid #f1f5f9" };
const TH: CSSProperties = { ...ROW, background: "#f8fafc", textAlign: "left", fontWeight: 600 };
const TD: CSSProperties = { ...ROW, fontFamily: "ui-monospace, monospace", fontSize: 12 };
const CARD: CSSProperties = {
  border: "1px solid #e5e7eb", borderRadius: 6, padding: 12,
  background: "#fafafa", marginBottom: 12,
};
const PILL_BASE: CSSProperties = {
  display: "inline-block", padding: "2px 8px", fontSize: 11,
  borderRadius: 999, fontFamily: "ui-monospace, monospace",
};
const PILL_OK: CSSProperties = { ...PILL_BASE, background: "#dcfce7", color: "#166534" };
const PILL_WARN: CSSProperties = { ...PILL_BASE, background: "#fef3c7", color: "#92400e" };
const PILL_ERR: CSSProperties = { ...PILL_BASE, background: "#fee2e2", color: "#991b1b" };
const PILL_INFO: CSSProperties = { ...PILL_BASE, background: "#dbeafe", color: "#1e40af" };

function pillFor(confidence?: string | null): CSSProperties {
  if (!confidence) return PILL_BASE;
  if (confidence === "high") return PILL_OK;
  if (confidence === "medium") return PILL_INFO;
  if (confidence === "low") return PILL_WARN;
  return PILL_ERR;
}

export default function AdminCommentTracePanel() {
  const [period, setPeriod] = useState<string>("");
  const [fund, setFund] = useState<string>("");
  const [showRaw, setShowRaw] = useState(false);

  const listQuery = useCommentTraceList(period || undefined, fund || undefined);
  const latestQuery = useCommentTraceLatest(period || undefined, fund || undefined);

  const items: TraceListItem[] = useMemo(
    () => (listQuery.data?.traces ?? []) as TraceListItem[],
    [listQuery.data],
  );

  const trace = latestQuery.data?.payload as Record<string, any> | undefined;

  // 옵션 추출 (list 결과에서 unique periods/funds)
  const periodOptions = useMemo(
    () => Array.from(new Set(items.map((i) => i.period))).sort().reverse(),
    [items],
  );
  const fundOptions = useMemo(
    () => Array.from(new Set(items.map((i) => i.fund_code))).sort(),
    [items],
  );

  return (
    <section>
      <h3 style={{ margin: "0 0 12px 0" }}>Comment Trace Viewer</h3>

      {/* Selectors */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13 }}>
          Period:&nbsp;
          <select value={period} onChange={(e) => setPeriod(e.target.value)}
                  style={{ padding: 4, fontSize: 13 }}>
            <option value="">(all)</option>
            {periodOptions.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>
          Fund:&nbsp;
          <select value={fund} onChange={(e) => setFund(e.target.value)}
                  style={{ padding: 4, fontSize: 13 }}>
            <option value="">(all)</option>
            {fundOptions.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        <button
          onClick={() => latestQuery.refetch()}
          style={{ padding: "4px 12px", fontSize: 13, cursor: "pointer" }}
        >
          Reload Latest
        </button>
      </div>

      {/* List */}
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Available Traces ({items.length})
        </div>
        {listQuery.isLoading && <div>Loading…</div>}
        {listQuery.error && <div style={PILL_ERR}>list 로딩 실패</div>}
        {!listQuery.isLoading && items.length === 0 && (
          <div style={{ fontSize: 12, color: "#6b7280" }}>
            등록된 trace 없음. <code>python tools/comment_trace.py
            --period &lt;P&gt; --fund &lt;F&gt;</code> 로 생성하세요.
          </div>
        )}
        {items.length > 0 && (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                <th style={TH}>trace_id</th>
                <th style={TH}>fund</th>
                <th style={TH}>period</th>
                <th style={TH}>nodes</th>
                <th style={TH}>edges</th>
                <th style={TH}>warn</th>
                <th style={TH}>err</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.trace_id}>
                  <td style={TD}>{it.trace_id}</td>
                  <td style={TD}>{it.fund_code}</td>
                  <td style={TD}>{it.period}</td>
                  <td style={TD}>{it.graph_node_count ?? 0}</td>
                  <td style={TD}>{it.graph_edge_count ?? 0}</td>
                  <td style={TD}>
                    {(it.warning_count ?? 0) > 0
                      ? <span style={PILL_WARN}>{it.warning_count}</span>
                      : 0}
                  </td>
                  <td style={TD}>
                    {(it.error_count ?? 0) > 0
                      ? <span style={PILL_ERR}>{it.error_count}</span>
                      : 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Latest summary */}
      {latestQuery.isLoading && <div>Latest 로딩…</div>}
      {latestQuery.error && (
        <div style={CARD}>
          <span style={PILL_ERR}>latest 응답 없음 (404)</span>
          <div style={{ fontSize: 12, marginTop: 6, color: "#6b7280" }}>
            period / fund 필터에 해당하는 trace 가 없습니다.
          </div>
        </div>
      )}
      {trace && <TraceDetail trace={trace} showRaw={showRaw}
                              onToggleRaw={() => setShowRaw((s) => !s)} />}
    </section>
  );
}

function TraceDetail({
  trace, showRaw, onToggleRaw,
}: { trace: Record<string, any>; showRaw: boolean; onToggleRaw: () => void }) {
  const ms = trace.market_source ?? {};
  const summary = trace.attribution_method_summary ?? {};
  const sections: any[] = trace.section_attribution ?? [];
  const graph = trace.graph_seed ?? { nodes: [], edges: [] };
  const sources = trace.sources ?? {};
  const warnings: string[] = trace.warnings ?? [];
  const errors: string[] = trace.errors ?? [];
  const ds = sources.data_snapshot ?? {};

  // node/edge type 별 count
  const nodeCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const n of graph.nodes ?? []) m[n.type] = (m[n.type] ?? 0) + 1;
    return m;
  }, [graph.nodes]);
  const edgeCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const e of graph.edges ?? []) m[e.type] = (m[e.type] ?? 0) + 1;
    return m;
  }, [graph.edges]);

  return (
    <>
      {/* Summary card */}
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Trace Summary
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 4, fontSize: 12 }}>
          <div>trace_id</div><div style={{ fontFamily: "ui-monospace, monospace" }}>{trace.trace_id}</div>
          <div>fund / period</div><div>{trace.fund_code} @ {trace.period}</div>
          <div>generated_at</div><div>{trace.generated_at}</div>
          <div>schema_version</div><div>{trace.schema_version}</div>
          <div>market_source.kind</div><div>{ms.kind}</div>
          <div>matched_by</div><div>{ms.matched_by}</div>
          <div>confidence</div>
          <div><span style={pillFor(ms.confidence)}>{ms.confidence}</span></div>
          <div>attribution_level</div><div>{trace.attribution_level}</div>
          <div>attribution_method_summary</div>
          <div>{Object.entries(summary)
                .map(([k, v]) => `${k}=${v}`).join(" / ")}</div>
          <div>graph nodes / edges</div>
          <div>{(graph.nodes ?? []).length} / {(graph.edges ?? []).length}</div>
          <div>warnings / errors</div>
          <div>
            {warnings.length > 0
              ? <span style={PILL_WARN}>{warnings.length} warnings</span>
              : <span style={PILL_OK}>0 warnings</span>}
            &nbsp;
            {errors.length > 0 && <span style={PILL_ERR}>{errors.length} errors</span>}
          </div>
        </div>
        {warnings.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 11 }}>
            {warnings.map((w, i) => (
              <div key={i} style={{ padding: 2, color: "#92400e" }}>⚠ {w}</div>
            ))}
          </div>
        )}
      </div>

      {/* Section attribution table */}
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Section Attribution ({sections.length})
        </div>
        {sections.length === 0
          ? <div style={{ fontSize: 12, color: "#6b7280" }}>section 없음</div>
          : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr>
                <th style={TH}>section_title</th>
                <th style={TH}>method</th>
                <th style={TH}>refs</th>
                <th style={TH}>evidence</th>
                <th style={TH}>wiki</th>
                <th style={TH}>asset</th>
                <th style={TH}>fund_data_keys</th>
                <th style={TH}>warn</th>
              </tr>
            </thead>
            <tbody>
              {sections.map((s: any, i: number) => (
                <tr key={i}>
                  <td style={TD}>{s.section_title}</td>
                  <td style={TD}>
                    <span style={s.attribution_method === "explicit_ref"
                      ? PILL_OK : PILL_INFO}>
                      {s.attribution_method}
                    </span>
                  </td>
                  <td style={TD}>{(s.ref_ids ?? []).length}</td>
                  <td style={TD}>{(s.evidence_ids ?? []).length}</td>
                  <td style={TD}>{(s.wiki_pages ?? []).length}</td>
                  <td style={TD}>{(s.asset_classes_mentioned ?? []).join(", ") || "—"}</td>
                  <td style={TD}>{(s.fund_data_keys ?? []).join(", ") || "—"}</td>
                  <td style={TD}>{(s.warnings ?? []).length || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Source groups */}
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Source Groups</div>
        <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 4, fontSize: 12 }}>
          <div>evidence_annotations</div>
          <div>{(sources.evidence_annotations ?? []).length}</div>
          <div>pinned_fund_context</div>
          <div>{sources.pinned_fund_context ? "있음" : "없음"}</div>
          <div>data_snapshot.fund_return</div>
          <div>
            {ds.fund_return == null
              ? <span style={PILL_WARN}>없음 — Q-FIX-2 이전 draft 또는 trace source 한계</span>
              : <span style={PILL_OK}>{ds.fund_return}</span>}
          </div>
          <div>data_snapshot.bm_count</div><div>{ds.bm_count ?? "—"}</div>
          <div>wiki_pages_selected</div>
          <div>{(sources.wiki_pages_selected ?? []).length}</div>
          <div>pa_classes</div><div>{(sources.pa_classes ?? []).length}</div>
          <div>holdings_top3</div><div>{(sources.holdings_top3 ?? []).length}</div>
        </div>
      </div>

      {/* Graph seed summary */}
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Graph Seed Summary (visualization 다음 단계)
        </div>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 12 }}>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>node_type counts</div>
            {Object.entries(nodeCounts).map(([k, v]) =>
              <div key={k}>{k}: <strong>{v}</strong></div>)}
          </div>
          <div>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>edge_type counts</div>
            {Object.entries(edgeCounts).map(([k, v]) =>
              <div key={k}>{k}: <strong>{v}</strong></div>)}
          </div>
        </div>
        <div style={{ marginTop: 12, fontSize: 11, color: "#6b7280" }}>
          nodes sample (5):
          <pre style={{ background: "#f3f4f6", padding: 6, fontSize: 10,
                         overflow: "auto", maxHeight: 120 }}>
            {JSON.stringify((graph.nodes ?? []).slice(0, 5), null, 2)}
          </pre>
          edges sample (5):
          <pre style={{ background: "#f3f4f6", padding: 6, fontSize: 10,
                         overflow: "auto", maxHeight: 120 }}>
            {JSON.stringify((graph.edges ?? []).slice(0, 5), null, 2)}
          </pre>
        </div>
      </div>

      {/* Raw JSON */}
      <div style={CARD}>
        <button onClick={onToggleRaw}
                style={{ padding: "4px 10px", fontSize: 12, cursor: "pointer" }}>
          {showRaw ? "Hide" : "Show"} Raw JSON
        </button>
        {showRaw && (
          <pre style={{ background: "#f3f4f6", padding: 8, fontSize: 10,
                         overflow: "auto", maxHeight: 480, marginTop: 8 }}>
            {JSON.stringify(trace, null, 2)}
          </pre>
        )}
      </div>
    </>
  );
}
