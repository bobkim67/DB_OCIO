import type { CSSProperties } from "react";
import MetaBadge from "../components/common/MetaBadge";
import type { ReportFinalResponseDTO } from "../api/endpoints";

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
  marginTop: 16,
  marginBottom: 8,
  color: "#111827",
};

const LIST_ITEM: CSSProperties = {
  fontSize: 13,
  lineHeight: 1.6,
  marginBottom: 6,
};

function fmtDt(s: string | null | undefined): string {
  if (!s) return "—";
  // ISO datetime → YYYY-MM-DD HH:MM
  return s.replace("T", " ").slice(0, 16);
}

/**
 * Approved final.json 의 client-노출 view.
 * 시장/펀드 모두 동일 레이아웃: 메타 → final_comment → consensus_points → tail_risks.
 * 빈 list (펀드 코멘트 다수)는 섹션 자체를 숨김.
 */
export default function ReportFinalView({
  data,
}: {
  data: ReportFinalResponseDTO;
}) {
  const d = data.data;
  const cp = d.consensus_points ?? [];
  const tr = d.tail_risks ?? [];

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
    </section>
  );
}
