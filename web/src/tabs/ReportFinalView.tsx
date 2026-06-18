import { useState, type CSSProperties } from "react";
import MetaBadge from "../components/common/MetaBadge";
import CommentMarkdown from "../components/common/CommentMarkdown";
import type {
  ClaimCitationDTO,
  EvidenceAnnotationDTO,
  EvidenceQualitySummaryDTO,
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

// 접기/펼치기 섹션 — 기본 숨김. 헤더 클릭으로 토글.
function Collapsible({
  title, count, defaultOpen = false, children,
}: {
  title: string;
  count: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{ ...SECTION_TITLE, cursor: "pointer", userSelect: "none" }}
      >
        <span style={{ display: "inline-block", width: 14, color: "#6b7280" }}>
          {open ? "▼" : "▶"}
        </span>
        {title} ({count})
      </div>
      {open && children}
    </>
  );
}

// Evidence = 인용된 claim 들의 원천 기사 (claim provenance). e{n} 으로 표기.
function EvidenceSection({ items }: { items: EvidenceAnnotationDTO[] }) {
  if (!items || items.length === 0) return null;
  return (
    <Collapsible title="Evidence · claim 원천 기사" count={items.length}>
      <table style={TABLE_STYLE}>
        <thead>
          <tr>
            <th style={{ ...TH, width: 40 }}>#</th>
            <th style={TH}>원천 기사</th>
            <th style={{ ...TH, width: 110 }}>매체</th>
            <th style={{ ...TH, width: 90 }}>날짜</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.ref}>
              <td style={{ ...TD, fontWeight: 600 }}>e{it.ref}</td>
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
            </tr>
          ))}
        </tbody>
      </table>
    </Collapsible>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Related News section
// ──────────────────────────────────────────────────────────────────────

// 본문 [c1]·[c2]… inline 인용에 대응하는 research claim 리스트.
const STANCE_COLOR: Record<string, { bg: string; fg: string }> = {
  bullish: { bg: "#fee2e2", fg: "#991b1b" },
  bearish: { bg: "#dbeafe", fg: "#1e40af" },
  neutral: { bg: "#f3f4f6", fg: "#374151" },
};

function ClaimsSection({ items }: { items: ClaimCitationDTO[] }) {
  if (!items || items.length === 0) return null;
  return (
    <Collapsible title="Claims" count={items.length}>
      <table style={TABLE_STYLE}>
        <thead>
          <tr>
            <th style={{ ...TH, width: 40 }}>#</th>
            <th style={TH}>리서치 claim</th>
            <th style={{ ...TH, width: 84 }}>자산군</th>
            <th style={{ ...TH, width: 70 }}>방향</th>
            <th style={{ ...TH, width: 110 }}>원천(e#)</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => {
            const sc = it.stance ? STANCE_COLOR[it.stance] ?? STANCE_COLOR.neutral : null;
            const refs = it.evidence_refs ?? [];
            return (
              <tr key={it.n}>
                <td style={{ ...TD, fontWeight: 600 }}>c{it.n}</td>
                <td style={TD}>{it.claim_text}</td>
                <td style={TD}>{it.asset_class ?? "—"}</td>
                <td style={TD}>
                  {it.stance && sc ? (
                    <span style={{ ...PILL_BASE, background: sc.bg, color: sc.fg }}>
                      {it.stance}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td style={TD}>
                  {refs.length > 0
                    ? refs.map((r) => `e${r}`).join(", ")
                    : (it.evidence_count ? `${it.evidence_count}건` : "—")}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Collapsible>
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
        <div style={COMMENT_BOX}>
          <CommentMarkdown text={d.final_comment} />
        </div>
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
          <ClaimsSection items={enr.claims ?? []} />
          <QualitySection q={enr.evidence_quality} />
          <ValidationSection v={enr.validation_summary} />
        </>
      )}

      {/* P3: 펀드 viewer 전용 — 동일 기간 시장 debate 의 evidence/news fan-out.
          시장 코멘트(_market) 자체 응답에는 market_enrichment 가 없으므로 표시 안 됨. */}
      {d.fund_code !== "_market" && d.market_enrichment && (
        <LinkedMarketSection linked={d.market_enrichment} />
      )}
    </section>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Linked Market Evidence section (P3 — 펀드 report 전용)
// ──────────────────────────────────────────────────────────────────────

function LinkedMarketSection({
  linked,
}: {
  linked: NonNullable<ReportFinalResponseDTO["data"]["market_enrichment"]>;
}) {
  const ev = linked.evidence_annotations ?? [];
  const hasContent = ev.length > 0;

  // 시장 evidence 가 비어 있으면 섹션 자체를 hide (related news 는 미노출)
  if (!hasContent) return null;

  return (
    <>
      <div style={SECTION_TITLE}>참고 시장 판단 근거</div>
      <div
        style={{
          background: "#eff6ff",
          border: "1px solid #bfdbfe",
          borderRadius: 6,
          padding: "8px 12px",
          fontSize: 12,
          color: "#1e40af",
          marginBottom: 8,
        }}
      >
        이 섹션은 펀드 코멘트 작성 시 참조한 동일 기간의 시장 debate 근거입니다.
        펀드 자체 보유 종목 근거가 아니라 시장 판단 근거입니다.
      </div>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>
        시장 기간: {linked.market_period}
        {linked.market_period_fallback && (
          <span style={{ color: "#92400e", marginLeft: 6 }}>
            (fund period fallback)
          </span>
        )}
      </div>
      {ev.length > 0 && <EvidenceSection items={ev} />}
    </>
  );
}
