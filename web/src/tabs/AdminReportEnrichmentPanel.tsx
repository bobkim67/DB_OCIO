import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useAdminDebatePeriods } from "../hooks/useAdminDebatePeriods";
import { useAdminReportEnrichmentDiagnosis } from "../hooks/useAdminReportEnrichmentDiagnosis";
import { useFunds } from "../hooks/useFunds";
import MetaBadge from "../components/common/MetaBadge";
import type {
  AdminEnrichmentJsonlRowDTO,
  InternalReportEnrichmentDTO,
  ReportEnrichmentFinalStatus,
} from "../api/endpoints";

const MARKET_OPTION = "_market";

const PRE_BOX: CSSProperties = {
  background: "#0f172a",
  color: "#e2e8f0",
  padding: 12,
  borderRadius: 6,
  fontSize: 12,
  lineHeight: 1.5,
  maxHeight: 360,
  overflow: "auto",
  margin: 0,
  whiteSpace: "pre",
};

const PILL: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 999,
  fontSize: 12,
  fontWeight: 600,
};

const META_CARD: CSSProperties = {
  background: "#f9fafb",
  border: "1px solid #e5e7eb",
  borderRadius: 6,
  padding: 10,
  fontSize: 12,
  minWidth: 200,
};

const TABLE_STYLE: CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 12,
};

const TH: CSSProperties = {
  background: "#f3f4f6",
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "1px solid #e5e7eb",
  fontWeight: 600,
};

const TD: CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid #f3f4f6",
  verticalAlign: "top",
  fontFamily: "monospace",
};

const NOTICE_BOX: CSSProperties = {
  background: "#fef3c7",
  border: "1px solid #fcd34d",
  borderRadius: 6,
  padding: "8px 12px",
  fontSize: 12,
  color: "#92400e",
  marginBottom: 16,
};

function finalStatusPill(s: ReportEnrichmentFinalStatus | undefined): CSSProperties {
  switch (s) {
    case "approved":
      return { ...PILL, background: "#dcfce7", color: "#166534" };
    case "final_unapproved":
      return { ...PILL, background: "#fed7aa", color: "#9a3412" };
    case "draft_only":
      return { ...PILL, background: "#dbeafe", color: "#1e40af" };
    case "not_generated":
    default:
      return { ...PILL, background: "#f3f4f6", color: "#6b7280" };
  }
}

function consistencyPill(status: string | undefined): CSSProperties {
  if (status === "matched_by_id" || status === "matched")
    return { ...PILL, background: "#dcfce7", color: "#166534" };
  if (status === "older_than_or_equal_final")
    return { ...PILL, background: "#d1fae5", color: "#065f46" };
  if (status === "id_mismatch" || status === "newer_than_final")
    return { ...PILL, background: "#fee2e2", color: "#991b1b" };
  if (status === "unverifiable")
    return { ...PILL, background: "#fef3c7", color: "#92400e" };
  return { ...PILL, background: "#f3f4f6", color: "#6b7280" };
}

function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

function fmtDt(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace("T", " ").slice(0, 19);
}

function PrettyJson({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <div style={{ color: "#6b7280", fontSize: 12 }}>없음</div>;
  }
  return <pre style={PRE_BOX}>{JSON.stringify(value, null, 2)}</pre>;
}

function InternalSourceTable({ enr }: { enr: InternalReportEnrichmentDTO }) {
  const rows = [
    ["evidence_annotations", enr.evidence_annotations_source,
      enr.evidence_annotations_internal_source,
      enr.evidence_annotations.length],
    ["related_news", enr.related_news_source,
      enr.related_news_internal_source,
      enr.related_news.length],
    ["evidence_quality", enr.evidence_quality_source,
      enr.evidence_quality_internal_source,
      enr.evidence_quality ? 1 : 0],
    ["validation_summary", enr.validation_summary_source,
      enr.validation_summary_internal_source,
      enr.validation_summary?.sanitize_warnings.length ?? 0],
    ["indicator_chart", enr.indicator_chart_source,
      enr.indicator_chart_internal_source,
      enr.indicator_chart?.series.length ?? 0],
  ] as const;
  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <th style={TH}>section</th>
          <th style={TH}>client source</th>
          <th style={TH}>internal source</th>
          <th style={TH}>count</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([name, ext, int, cnt]) => (
          <tr key={name}>
            <td style={TD}>{name}</td>
            <td style={TD}>{ext}</td>
            <td style={TD}>{int}</td>
            <td style={TD}>{cnt}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function JsonlRowsTable({ rows }: { rows: AdminEnrichmentJsonlRowDTO[] }) {
  if (rows.length === 0) {
    return <div style={{ color: "#6b7280", fontSize: 12 }}>매칭 row 없음</div>;
  }
  return (
    <table style={TABLE_STYLE}>
      <thead>
        <tr>
          <th style={TH}>debated_at</th>
          <th style={TH}>debate_run_id</th>
          <th style={TH}>cited</th>
          <th style={TH}>selected</th>
          <th style={TH}>uncited</th>
          <th style={TH}>ref_mismatch</th>
          <th style={TH}>mismatch_rate</th>
          <th style={TH}>critical</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i}>
            <td style={TD}>{fmtDt(r.debated_at)}</td>
            <td style={TD}>{shortId(r.debate_run_id)}</td>
            <td style={TD}>{r.cited_ref_count ?? "—"}</td>
            <td style={TD}>{r.selected_evidence_count ?? "—"}</td>
            <td style={TD}>{r.uncited_evidence_count ?? "—"}</td>
            <td style={TD}>{r.ref_mismatches ?? "—"}</td>
            <td style={TD}>
              {r.mismatch_rate != null ? r.mismatch_rate.toFixed(3) : "—"}
            </td>
            <td style={TD}>{r.critical_warnings ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AdminReportEnrichmentPanel() {
  const periodsQuery = useAdminDebatePeriods();
  const fundsQuery = useFunds();

  const [period, setPeriod] = useState<string>("");
  const [fund, setFund] = useState<string>("");

  const periodOptions = useMemo(
    () => periodsQuery.data?.periods ?? [],
    [periodsQuery.data],
  );
  const fundOptions = useMemo(() => {
    const xs = fundsQuery.data?.data?.map((f) => f.code) ?? [];
    return [MARKET_OPTION, ...xs];
  }, [fundsQuery.data]);

  // 자동 첫 항목 선택
  useEffect(() => {
    if (!period && periodOptions.length > 0) setPeriod(periodOptions[0]);
  }, [period, periodOptions]);
  useEffect(() => {
    if (!fund && fundOptions.length > 0) setFund(fundOptions[0]);
  }, [fund, fundOptions]);

  const diag = useAdminReportEnrichmentDiagnosis(period, fund);

  const data = diag.data;
  const idMatchVisual: string =
    data && data.approved_debate_run_id && data.draft_run_id
      ? data.approved_debate_run_id === data.draft_run_id ? "✓ ID 일치" : "✗ ID 불일치"
      : data?.approved_debate_run_id || data?.draft_run_id
        ? "— (한쪽만 보유)"
        : "— (legacy 또는 미생성)";

  return (
    <section>
      <div style={NOTICE_BOX}>
        <strong>관리자 진단용 화면입니다.</strong>{" "}
        client report 에는 노출되지 않는 internal source 와 lineage 정보(debate_run_id /
        approved_debate_run_id / raw reason)를 표시합니다. 운영 환경에서는 인증/권한
        가드가 별도로 필요합니다.
      </div>

      {/* 셀렉터 */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        <label style={{ fontSize: 13 }}>
          period{" "}
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            style={{ padding: "4px 8px", fontSize: 13 }}
          >
            {periodOptions.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label style={{ fontSize: 13 }}>
          fund{" "}
          <select
            value={fund}
            onChange={(e) => setFund(e.target.value)}
            style={{ padding: "4px 8px", fontSize: 13 }}
          >
            {fundOptions.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
        {data && <MetaBadge meta={data.meta} />}
      </div>

      {diag.isLoading && <div style={{ fontSize: 13 }}>불러오는 중...</div>}
      {diag.isError && (
        <div style={{ color: "#991b1b", fontSize: 13 }}>
          에러: {(diag.error as Error)?.message ?? "unknown"}
        </div>
      )}

      {data && (
        <>
          {/* 메타 카드 */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
            <div style={META_CARD}>
              <div style={{ fontSize: 11, color: "#6b7280" }}>final_status</div>
              <div style={{ marginTop: 4 }}>
                <span style={finalStatusPill(data.final_status)}>
                  {data.final_status}
                </span>
              </div>
            </div>
            <div style={META_CARD}>
              <div style={{ fontSize: 11, color: "#6b7280" }}>
                approved_debate_run_id
              </div>
              <div style={{ fontFamily: "monospace", marginTop: 4 }}>
                {shortId(data.approved_debate_run_id)}
              </div>
              <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>
                approved_at: {fmtDt(data.approved_at)}
              </div>
            </div>
            <div style={META_CARD}>
              <div style={{ fontSize: 11, color: "#6b7280" }}>draft_run_id</div>
              <div style={{ fontFamily: "monospace", marginTop: 4 }}>
                {shortId(data.draft_run_id)}
              </div>
              <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 2 }}>
                draft_generated_at: {fmtDt(data.draft_generated_at)}
              </div>
            </div>
            <div style={META_CARD}>
              <div style={{ fontSize: 11, color: "#6b7280" }}>ID 일치</div>
              <div style={{ marginTop: 4, fontWeight: 600 }}>{idMatchVisual}</div>
            </div>
          </div>

          {/* lineage 진단 */}
          {data.enrichment && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                Lineage 진단
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center",
                            marginBottom: 6 }}>
                <span style={consistencyPill(
                  data.enrichment.source_consistency_status,
                )}>
                  {data.enrichment.source_consistency_status}
                </span>
              </div>
              {data.enrichment.source_consistency_reason && (
                <div style={{ fontSize: 12, color: "#374151",
                              background: "#f9fafb", border: "1px solid #e5e7eb",
                              borderRadius: 4, padding: "6px 8px" }}>
                  <strong>raw reason:</strong>{" "}
                  {data.enrichment.source_consistency_reason}
                </div>
              )}
            </div>
          )}

          {/* internal source table */}
          {data.enrichment && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
                Section 별 source
              </div>
              <InternalSourceTable enr={data.enrichment} />
            </div>
          )}

          {/* jsonl rows */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6 }}>
              evidence_quality.jsonl rows
              <span style={{ fontSize: 11, color: "#6b7280", marginLeft: 8 }}>
                (returned {data.jsonl_returned} / total matched{" "}
                {data.jsonl_total_matched})
              </span>
            </div>
            <JsonlRowsTable rows={data.jsonl_rows} />
          </div>

          {/* 원본 enrichment JSON (collapsible) */}
          {data.enrichment && (
            <details style={{ marginTop: 12 }}>
              <summary style={{ fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
                ▶ Internal Enrichment 원본 JSON (admin/debug 전용)
              </summary>
              <div style={{ marginTop: 8 }}>
                <PrettyJson value={data.enrichment} />
              </div>
            </details>
          )}
        </>
      )}
    </section>
  );
}
