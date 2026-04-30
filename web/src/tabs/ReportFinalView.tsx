import type { CSSProperties } from "react";
import MetaBadge from "../components/common/MetaBadge";
import IndicatorChart from "../components/charts/IndicatorChart";
import type {
  EvidenceAnnotationDTO,
  EvidenceQualitySummaryDTO,
  IndicatorChartDTO,
  RelatedNewsDTO,
  ReportFinalResponseDTO,
  ValidationSummaryDTO,
} from "../api/endpoints";

const COMMENT_BOX: CSSProperties = {
  background: "#f9fafb",
  border: "1px solid #e5e7eb",
  borderRadius: 6,
  padding: 16,
  fontSize: 14,
  lineHeight: 1.7,
  whiteSpace: "pre-wrap",
  marginBottom: 16,
};

const META_ROW: CSSProperties = {
  display: "flex",
  gap: 16,
  flexWrap: "wrap",
  fontSize: 12,
  color: "#6b7280",
  marginBottom: 12,
};

const SECTION_TITLE: CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  marginTop: 20,
  marginBottom: 8,
  color: "#111827",
};

const LIST_ITEM: CSSProperties = {
  fontSize: 13,
  lineHeight: 1.6,
  marginBottom: 6,
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
};

const PILL_BASE: CSSProperties = {
  display: "inline-block",
  padding: "1px 6px",
  borderRadius: 4,
  fontSize: 11,
  fontWeight: 500,
};

function fmtDt(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace("T", " ").slice(0, 16);
}

function severityPill(severity: string) {
  const colors: Record<string, { bg: string; fg: string }> = {
    critical: { bg: "#fee2e2", fg: "#991b1b" },
    warning: { bg: "#fef3c7", fg: "#92400e" },
    info: { bg: "#dbeafe", fg: "#1e40af" },
  };
  const c = colors[severity] ?? { bg: "#e5e7eb", fg: "#374151" };
  return (
    <span style={{ ...PILL_BASE, background: c.bg, color: c.fg }}>
      {severity}
    </span>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Evidence section
// ──────────────────────────────────────────────────────────────────────

function EvidenceSection({ items }: { items: EvidenceAnnotationDTO[] }) {
  if (!items || items.length === 0) return null;
  return (
    <>
      <div style={SECTION_TITLE}>Evidence ({items.length})</div>
      <table style={TABLE_STYLE}>
        <thead>
          <tr>
            <th style={{ ...TH, width: 36 }}>ref</th>
            <th style={TH}>제목</th>
            <th style={{ ...TH, width: 100 }}>매체</th>
            <th style={{ ...TH, width: 90 }}>날짜</th>
            <th style={{ ...TH, width: 100 }}>토픽</th>
            <th style={{ ...TH, width: 60 }}>중요도</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.ref}>
              <td style={TD}>{it.ref}</td>
              <td style={TD}>
                {it.url ? (
                  <a href={it.url} target="_blank" rel="noreferrer"
                     style={{ color: "#1d4ed8", textDecoration: "none" }}>
                    {it.title ?? "(제목 없음)"}
                  </a>
                ) : (
                  it.title ?? "(제목 없음)"
                )}
              </td>
              <td style={TD}>{it.source ?? "—"}</td>
              <td style={TD}>{it.date ?? "—"}</td>
              <td style={TD}>{it.topic ?? "—"}</td>
              <td style={TD}>
                {typeof it.salience === "number"
                  ? it.salience.toFixed(2)
                  : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Related News section
// ──────────────────────────────────────────────────────────────────────

function RelatedNewsSection({ items }: { items: RelatedNewsDTO[] }) {
  if (!items || items.length === 0) return null;
  return (
    <>
      <div style={SECTION_TITLE}>Related News ({items.length})</div>
      <table style={TABLE_STYLE}>
        <thead>
          <tr>
            <th style={TH}>제목</th>
            <th style={{ ...TH, width: 100 }}>매체</th>
            <th style={{ ...TH, width: 90 }}>날짜</th>
            <th style={{ ...TH, width: 100 }}>토픽</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={`${it.article_id ?? i}`}>
              <td style={TD}>
                {it.url ? (
                  <a href={it.url} target="_blank" rel="noreferrer"
                     style={{ color: "#1d4ed8", textDecoration: "none" }}>
                    {it.title ?? "(제목 없음)"}
                  </a>
                ) : (
                  it.title ?? "(제목 없음)"
                )}
              </td>
              <td style={TD}>{it.source ?? "—"}</td>
              <td style={TD}>{it.date ?? "—"}</td>
              <td style={TD}>{it.topic ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Quality section
// ──────────────────────────────────────────────────────────────────────

function QualitySection({ q }: { q: EvidenceQualitySummaryDTO | null | undefined }) {
  if (!q) return null;

  type Cell = [string, string];
  const cells: Cell[] = [];
  // 신규 명시 필드 우선 (의미 분리)
  const cited = q.cited_ref_count ?? q.total_refs ?? null;
  const selected = q.selected_evidence_count ?? q.evidence_count ?? null;
  const uncited = q.uncited_evidence_count ?? null;
  const mismatch = q.ref_mismatch_count ?? q.ref_mismatches ?? null;

  if (cited != null) cells.push(["인용 ref 수", String(cited)]);
  if (selected != null) cells.push(["선정 evidence", String(selected)]);
  if (uncited != null) cells.push(["미인용 evidence", String(uncited)]);
  if (mismatch != null) cells.push(["ref 오매핑", String(mismatch)]);
  if (q.tense_mismatches != null)
    cells.push(["시제 mismatch", String(q.tense_mismatches)]);
  if (q.mismatch_rate != null)
    cells.push(["mismatch_rate", q.mismatch_rate.toFixed(3)]);
  if (q.critical_warnings != null)
    cells.push(["critical 경고", String(q.critical_warnings)]);
  if (q.coverage_referenced_topics != null && q.coverage_available_topics != null)
    cells.push([
      "topic coverage",
      `${q.coverage_referenced_topics}/${q.coverage_available_topics}`,
    ]);
  if (q.numeric_sentences_total != null)
    cells.push(["수치 문장", String(q.numeric_sentences_total)]);
  if (q.uncited_numeric_count != null)
    cells.push(["미인용 수치", String(q.uncited_numeric_count)]);

  if (cells.length === 0) return null;

  return (
    <>
      <div style={SECTION_TITLE}>Evidence Quality</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {cells.map(([label, val]) => (
          <div key={label} style={{
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 6,
            padding: "8px 12px",
            minWidth: 130,
          }}>
            <div style={{ fontSize: 11, color: "#6b7280" }}>{label}</div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{val}</div>
          </div>
        ))}
      </div>
      {q.coverage_unreferenced_topics && q.coverage_unreferenced_topics.length > 0 && (
        <div style={{ fontSize: 12, color: "#6b7280", marginTop: 6 }}>
          미인용 토픽: {q.coverage_unreferenced_topics.join(", ")}
        </div>
      )}
      {q.debated_at && (
        <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 4 }}>
          debate 시각: {fmtDt(q.debated_at)}
        </div>
      )}
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Validation section
// ──────────────────────────────────────────────────────────────────────

// ──────────────────────────────────────────────────────────────────────
// Indicator Chart section (P1-③)
// macro context — approved final 의 period 범위로 read-time 합성한 참고 차트.
// 승인본의 근거 데이터가 아님을 사용자에게 명시한다.
// ──────────────────────────────────────────────────────────────────────

function IndicatorChartSection({
  chart,
}: {
  chart: IndicatorChartDTO | null | undefined;
}) {
  if (!chart || !chart.series || chart.series.length === 0) return null;
  return (
    <>
      <div style={SECTION_TITLE}>참고 시장지표</div>
      <div style={{
        background: "#fef3c7", border: "1px solid #fcd34d",
        borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#92400e",
        marginBottom: 8,
      }}>
        참고용 시장지표 차트입니다. 승인본 보고서의 근거 데이터가 아니라,
        보고서 기간에 맞춰 조회한 macro timeseries 입니다.
      </div>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>
        기간: {chart.period_start ?? "—"} ~ {chart.period_end ?? "—"} ·
        normalize: 첫 유효값 = 100
      </div>
      <IndicatorChart series={chart.series} />
    </>
  );
}


function ValidationSection({
  v,
}: {
  v: ValidationSummaryDTO | null | undefined;
}) {
  if (!v) return null;
  const counts = v.warning_counts ?? {};
  const warnings = v.sanitize_warnings ?? [];
  const hasCounts = Object.keys(counts).length > 0;
  if (!hasCounts && warnings.length === 0) return null;

  return (
    <>
      <div style={SECTION_TITLE}>Validation</div>
      {hasCounts && (
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          {Object.entries(counts).map(([k, v2]) => (
            <span key={k} style={{
              ...PILL_BASE,
              background: k === "critical" ? "#fee2e2"
                : k === "warning" ? "#fef3c7"
                  : "#dbeafe",
              color: k === "critical" ? "#991b1b"
                : k === "warning" ? "#92400e"
                  : "#1e40af",
            }}>
              {k}: {v2}
            </span>
          ))}
        </div>
      )}
      {warnings.length > 0 && (
        <table style={TABLE_STYLE}>
          <thead>
            <tr>
              <th style={{ ...TH, width: 80 }}>severity</th>
              <th style={{ ...TH, width: 130 }}>type</th>
              <th style={TH}>message</th>
              <th style={{ ...TH, width: 50 }}>ref</th>
            </tr>
          </thead>
          <tbody>
            {warnings.map((w, i) => (
              <tr key={i}>
                <td style={TD}>{severityPill(w.severity)}</td>
                <td style={TD}>{w.type}</td>
                <td style={TD}>{w.message}</td>
                <td style={TD}>{w.ref_no ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Main view
// ──────────────────────────────────────────────────────────────────────

/**
 * Approved final.json 의 client-노출 view.
 * 시장/펀드 모두 동일 레이아웃: 메타 → final_comment → consensus_points → tail_risks
 *   → enrichment(Evidence/RelatedNews/Quality/Validation).
 * 빈 list/null 섹션은 자체 hide.
 */
export default function ReportFinalView({
  data,
}: {
  data: ReportFinalResponseDTO;
}) {
  const d = data.data;
  const cp = d.consensus_points ?? [];
  const tr = d.tail_risks ?? [];
  const enr = d.enrichment;

  return (
    <section>
      <div style={{ display: "flex", gap: 12, alignItems: "center",
                    marginBottom: 12, flexWrap: "wrap" }}>
        <h3 style={{ fontSize: 15, margin: 0 }}>
          {d.fund_code === "_market"
            ? `시장 코멘트 · ${d.period}`
            : `${d.fund_code} 코멘트 · ${d.period}`}
        </h3>
        <MetaBadge meta={data.meta} />
      </div>

      <div style={META_ROW}>
        <span>승인: {fmtDt(d.approved_at)}</span>
        <span>승인자: {d.approved_by ?? "—"}</span>
        <span>생성: {fmtDt(d.generated_at)}</span>
        {d.model && <span>model: {d.model}</span>}
      </div>

      {d.final_comment ? (
        <div style={COMMENT_BOX}>{d.final_comment}</div>
      ) : (
        <div style={{ color: "#6b7280", fontSize: 13, marginBottom: 16 }}>
          코멘트가 비어 있습니다.
        </div>
      )}

      {cp.length > 0 && (
        <>
          <div style={SECTION_TITLE}>합의 포인트</div>
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            {cp.map((p, i) => (
              <li key={i} style={LIST_ITEM}>{p}</li>
            ))}
          </ul>
        </>
      )}

      {tr.length > 0 && (
        <>
          <div style={SECTION_TITLE}>테일 리스크</div>
          <ul style={{ paddingLeft: 20, margin: 0 }}>
            {tr.map((p, i) => (
              <li key={i} style={LIST_ITEM}>{p}</li>
            ))}
          </ul>
        </>
      )}

      {enr && (
        <>
          <EvidenceSection items={enr.evidence_annotations ?? []} />
          <RelatedNewsSection items={enr.related_news ?? []} />
          <QualitySection q={enr.evidence_quality} />
          <ValidationSection v={enr.validation_summary} />
          <IndicatorChartSection chart={enr.indicator_chart} />
        </>
      )}
    </section>
  );
}
