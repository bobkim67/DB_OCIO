// R5-A: Comment Trace Viewer (read-only).
// R5-B: graph_seed Obsidian-like force-directed view 추가 (AdminCommentTraceGraph).
//   - 기존 table/raw JSON viewer 그대로 유지
//   - Graph Seed Summary 아래에 Graph View 섹션 추가
import { useMemo, useState, type CSSProperties } from "react";
import {
  useCommentTraceList,
  useCommentTraceLatest,
} from "../hooks/useCommentTrace";
import AdminCommentTraceGraph from "./AdminCommentTraceGraph";

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
  const causalGraph = trace.graph_seed_causal ?? null;
  const causalPaths: any[] = trace.causal_paths ?? [];
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

      {/* R9-A.5-UI: Claim Citation Summary card. trace.claim_citation_summary
          가 backend payload 로 도달하면 표시. 없으면 빈 안내. */}
      <ClaimCitationSummaryCard summary={trace.claim_citation_summary} />

      {/* Section attribution table — R9-A.5-UI: claims 컬럼 추가 */}
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
                <th style={TH}>claims</th>
                <th style={TH}>asset</th>
                <th style={TH}>fund_data_keys</th>
                <th style={TH}>warn</th>
              </tr>
            </thead>
            <tbody>
              {sections.map((s: any, i: number) => {
                const claimRefCount = (s.claim_refs ?? []).length;
                const claimUnmatchedCount = (s.claim_unmatched ?? []).length;
                return (
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
                  <td style={TD}>
                    {claimRefCount === 0
                      ? "—"
                      : claimUnmatchedCount > 0
                        ? <span style={PILL_WARN}>
                            {claimRefCount} ({claimUnmatchedCount} unmatched)
                          </span>
                        : <span style={PILL_OK}>{claimRefCount}</span>}
                  </td>
                  <td style={TD}>{(s.asset_classes_mentioned ?? []).join(", ") || "—"}</td>
                  <td style={TD}>{(s.fund_data_keys ?? []).join(", ") || "—"}</td>
                  <td style={TD}>{(s.warnings ?? []).length || "—"}</td>
                </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* R9-A.5-UI: Linked Claims card — section_attribution 의
          claim_attributions 평면화 + matched / unmatched 분리. */}
      <LinkedClaimsCard sections={sections} />

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
          Graph Seed Summary
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

      {/* R5-B Graph View (cytoscape) */}
      <AdminCommentTraceGraph provenance={graph} causal={causalGraph} />

      {causalPaths.length > 0 && (
        <div style={CARD}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
            Causal Paths (R7) · {causalPaths.length}
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" as const, fontSize: 11 }}>
            <thead>
              <tr>
                <th style={TH}>path_id</th>
                <th style={TH}>label</th>
                <th style={TH}>cov</th>
                <th style={TH}>evidence</th>
                <th style={TH}>sections</th>
                <th style={TH}>conf</th>
              </tr>
            </thead>
            <tbody>
              {causalPaths.map((p) => (
                <tr key={p.path_id}>
                  <td style={TD}>{p.path_id}</td>
                  <td style={{ ...TD, fontFamily: "inherit" }}>{p.label}</td>
                  <td style={TD}>
                    {(p.covered_chain_nodes?.length ?? 0)}/{(p.chain?.length ?? 0)}
                  </td>
                  <td style={TD}>{p.supporting_evidence_ids?.length ?? 0}</td>
                  <td style={TD}>{p.linked_sections?.length ?? 0}</td>
                  <td style={TD}>{p.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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


// ──────────────────────────────────────────────────────────────────────
// R9-A.5-UI surface — Claim Citation Summary
// ──────────────────────────────────────────────────────────────────────

type ClaimCitationSummary = {
  total_claim_refs?: number;
  unique_matched_claims?: string[];
  unique_unmatched_hashes?: string[];
  matched_count?: number;
  unmatched_count?: number;
  sections_with_claim_count?: number;
  sections_without_claim_count?: number;
  canonical_pool_size?: number;
  load_warning?: string | null;
};

function ClaimCitationSummaryCard(
  { summary }: { summary?: ClaimCitationSummary | null },
) {
  if (!summary) {
    return (
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Claim Citation Summary (R9-A.5)
        </div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          claim trace 데이터 없음 — 이전 trace 또는 claim store 미연결
        </div>
      </div>
    );
  }
  const total = summary.total_claim_refs ?? 0;
  const matched = summary.matched_count ?? 0;
  const unmatched = summary.unmatched_count ?? 0;
  const pool = summary.canonical_pool_size ?? 0;
  const loadWarning = summary.load_warning;
  const matchPill = matched > 0 ? PILL_OK : PILL_INFO;
  return (
    <div style={CARD}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
        Claim Citation Summary (R9-A.5)
      </div>
      <div style={{ display: "grid",
                    gridTemplateColumns: "180px 1fr",
                    gap: 4, fontSize: 12 }}>
        <div>canonical_pool_size</div>
        <div>
          {pool === 0
            ? <span style={PILL_WARN}>0 (claim store 미연결)</span>
            : <strong>{pool}</strong>}
        </div>

        <div>total_claim_refs</div><div>{total}</div>

        <div>matched / unmatched</div>
        <div>
          <span style={matchPill}>matched {matched}</span>
          &nbsp;
          {unmatched > 0
            ? <span style={PILL_WARN}>unmatched {unmatched}</span>
            : <span style={PILL_OK}>unmatched 0</span>}
        </div>

        <div>sections (with / without)</div>
        <div>
          {summary.sections_with_claim_count ?? 0}
          &nbsp;/&nbsp;
          {summary.sections_without_claim_count ?? 0}
        </div>

        <div>unique_matched_claims</div>
        <div style={{ fontFamily: "ui-monospace, monospace", fontSize: 11 }}>
          {(summary.unique_matched_claims ?? []).length === 0
            ? "—"
            : (summary.unique_matched_claims ?? []).join(", ")}
        </div>

        <div>unique_unmatched_hashes</div>
        <div>
          {(summary.unique_unmatched_hashes ?? []).length === 0
            ? "—"
            : (summary.unique_unmatched_hashes ?? []).map((h) => (
                <span key={h} style={{ ...PILL_WARN, marginRight: 4 }}>
                  {h}
                </span>
              ))}
        </div>

        <div>load_warning</div>
        <div>
          {loadWarning
            ? <span style={PILL_WARN}>{loadWarning}</span>
            : <span style={PILL_OK}>none</span>}
        </div>
      </div>
    </div>
  );
}


// ──────────────────────────────────────────────────────────────────────
// R9-A.5-UI surface — Linked Claims
// ──────────────────────────────────────────────────────────────────────

type ClaimAttribution = {
  hash10?: string;
  claim_id?: string | null;
  wiki_path?: string | null;
  supporting_evidence_ids?: string[];
  claim_text_short?: string | null;
  matched?: boolean;
};

function LinkedClaimsCard({ sections }: { sections: any[] }) {
  // Flatten section_attribution[*].claim_attributions, dedup by (section_id, hash10)
  type Row = ClaimAttribution & { section_id: string; section_title?: string };
  const rows: Row[] = [];
  for (const s of sections ?? []) {
    const list: ClaimAttribution[] = s?.claim_attributions ?? [];
    for (const ca of list) {
      rows.push({
        ...ca,
        section_id: s?.section_id ?? "?",
        section_title: s?.section_title ?? "?",
      });
    }
  }

  if (rows.length === 0) {
    return (
      <div style={CARD}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Linked Claims (R9-A.5)
        </div>
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          [claim:hash10] 인용 없음 — LLM 출력에 canonical claim 인용이
          포함되지 않았거나 trace 가 R9-A.5 surface 이전 버전.
        </div>
      </div>
    );
  }

  const matchedRows = rows.filter((r) => r.matched);
  const unmatchedRows = rows.filter((r) => !r.matched);

  return (
    <div style={CARD}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
        Linked Claims (R9-A.5)
        &nbsp;
        <span style={PILL_OK}>matched {matchedRows.length}</span>
        &nbsp;
        {unmatchedRows.length > 0 && (
          <span style={PILL_WARN}>unmatched {unmatchedRows.length}</span>
        )}
      </div>
      {matchedRows.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse" as const,
                         fontSize: 12, marginBottom: 8 }}>
          <thead>
            <tr>
              <th style={TH}>hash10</th>
              <th style={TH}>claim_id</th>
              <th style={TH}>section</th>
              <th style={TH}>claim_text_short</th>
              <th style={TH}>wiki_path</th>
              <th style={TH}>evidence</th>
            </tr>
          </thead>
          <tbody>
            {matchedRows.map((r, i) => (
              <tr key={`m-${i}`}>
                <td style={TD}>{r.hash10 ?? "—"}</td>
                <td style={TD}>{r.claim_id ?? "—"}</td>
                <td style={TD}>{r.section_title ?? r.section_id}</td>
                <td style={{ ...TD, fontFamily: "inherit" }}>
                  {r.claim_text_short ?? "—"}
                </td>
                <td style={TD}>
                  {r.wiki_path
                    ? <span style={{ color: "#1d4ed8" }}>{r.wiki_path}</span>
                    : "—"}
                </td>
                <td style={TD}>
                  {(r.supporting_evidence_ids ?? []).length === 0
                    ? "—"
                    : (r.supporting_evidence_ids ?? []).join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {unmatchedRows.length > 0 && (
        <>
          <div style={{ fontSize: 12, fontWeight: 600,
                         marginTop: 8, marginBottom: 4 }}>
            Unmatched (warning)
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" as const,
                           fontSize: 12 }}>
            <thead>
              <tr>
                <th style={TH}>hash10</th>
                <th style={TH}>section</th>
                <th style={TH}>note</th>
              </tr>
            </thead>
            <tbody>
              {unmatchedRows.map((r, i) => (
                <tr key={`u-${i}`}>
                  <td style={TD}>
                    <span style={PILL_WARN}>{r.hash10 ?? "?"}</span>
                  </td>
                  <td style={TD}>{r.section_title ?? r.section_id}</td>
                  <td style={TD}>
                    canonical pool 밖 — promoted 아니거나 hash 오류
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
