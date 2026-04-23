import { useState, type CSSProperties } from "react";
import { useAdminEvidenceQuality } from "../hooks/useAdminEvidenceQuality";
import MetaBadge from "../components/common/MetaBadge";
import type { AdminEvidenceQualityRowDTO } from "../api/endpoints";

const LIMIT_OPTIONS = [20, 50, 100] as const;

function fmtPct(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function fmtInt(v: number | null): string {
  if (v === null || v === undefined) return "—";
  return String(v);
}

function fmtDt(v: string | null): string {
  if (!v) return "—";
  return v.replace("T", " ").slice(0, 19);
}

const TH: CSSProperties = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "1px solid #e5e7eb",
  background: "#f9fafb",
  fontWeight: 600,
  fontSize: 12,
  color: "#374151",
  whiteSpace: "nowrap",
};

const TD: CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid #f3f4f6",
  fontSize: 12,
  whiteSpace: "nowrap",
};

function rowColor(row: AdminEvidenceQualityRowDTO): string {
  const mm = row.mismatch_rate ?? 0;
  const crit = row.critical_warnings ?? 0;
  if (crit > 0) return "#fef2f2";
  if (mm >= 0.2) return "#fffbeb";
  return "transparent";
}

export default function AdminTab() {
  const [limit, setLimit] = useState<number>(50);
  const [fundInput, setFundInput] = useState<string>("");
  const [fundApplied, setFundApplied] = useState<string>("");

  const { data, isLoading, error } = useAdminEvidenceQuality(
    limit,
    fundApplied || undefined,
  );

  const apply = () => {
    setFundApplied(fundInput.trim());
  };

  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>
          Admin · Evidence Quality
        </h2>
        {data && <MetaBadge meta={data.meta} />}
      </div>

      <div
        style={{
          display: "flex",
          gap: 12,
          marginBottom: 12,
          fontSize: 13,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <label>
          limit:&nbsp;
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            style={{ fontSize: 13, padding: "3px 6px" }}
          >
            {LIMIT_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>

        <label>
          fund_code:&nbsp;
          <input
            type="text"
            value={fundInput}
            onChange={(e) => setFundInput(e.target.value)}
            placeholder="예: 07G04 · _market · 빈칸=전체"
            style={{
              fontSize: 13,
              padding: "3px 6px",
              width: 180,
              border: "1px solid #d1d5db",
              borderRadius: 4,
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") apply();
            }}
          />
        </label>
        <button
          onClick={apply}
          style={{
            padding: "4px 12px",
            fontSize: 13,
            border: "1px solid #2563eb",
            background: "#2563eb",
            color: "#fff",
            borderRadius: 4,
            cursor: "pointer",
          }}
        >
          적용
        </button>
        {fundApplied && (
          <span style={{ color: "#6b7280", fontSize: 12 }}>
            필터: <strong>{fundApplied}</strong>
          </span>
        )}
      </div>

      {isLoading ? (
        <div>loading evidence-quality...</div>
      ) : error || !data ? (
        <div style={{ color: "#6b7280", padding: 16 }}>
          데이터 없음 (파일 없음 또는 읽기 실패)
        </div>
      ) : (
        <>
          <div
            style={{
              fontSize: 12,
              color: "#6b7280",
              marginBottom: 8,
              fontFamily: "monospace",
            }}
          >
            file_path: <span style={{ color: "#374151" }}>{data.file_path}</span>
            &nbsp;·&nbsp; total_lines: <strong>{data.total_lines}</strong>
            &nbsp;·&nbsp; returned: <strong>{data.returned}</strong>
            &nbsp;·&nbsp; malformed:{" "}
            <strong
              style={{ color: data.malformed > 0 ? "#b45309" : "#374151" }}
            >
              {data.malformed}
            </strong>
          </div>

          {data.rows.length === 0 ? (
            <div style={{ color: "#6b7280", padding: 16 }}>
              데이터 없음 (파일 없음 또는 읽기 실패)
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table
                style={{
                  borderCollapse: "collapse",
                  width: "100%",
                  minWidth: 900,
                }}
              >
                <thead>
                  <tr>
                    <th style={TH}>fund_code</th>
                    <th style={TH}>period</th>
                    <th style={TH}>debated_at</th>
                    <th style={{ ...TH, textAlign: "right" }}>total_refs</th>
                    <th
                      style={{
                        ...TH,
                        textAlign: "right",
                        color: "#b91c1c",
                      }}
                    >
                      ref_mismatches
                    </th>
                    <th
                      style={{
                        ...TH,
                        textAlign: "right",
                        color: "#b91c1c",
                      }}
                    >
                      critical_warnings
                    </th>
                    <th style={{ ...TH, textAlign: "right" }}>
                      tense_mismatches
                    </th>
                    <th style={{ ...TH, textAlign: "right" }}>
                      mismatch_rate
                    </th>
                    <th style={{ ...TH, textAlign: "right" }}>
                      evidence_count
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr
                      key={i}
                      style={{ background: rowColor(row) }}
                    >
                      <td style={TD}>{row.fund_code ?? "—"}</td>
                      <td style={TD}>{row.period ?? "—"}</td>
                      <td style={TD}>{fmtDt(row.debated_at)}</td>
                      <td style={{ ...TD, textAlign: "right" }}>
                        {fmtInt(row.total_refs)}
                      </td>
                      <td
                        style={{
                          ...TD,
                          textAlign: "right",
                          color:
                            (row.ref_mismatches ?? 0) > 0
                              ? "#b91c1c"
                              : "#374151",
                        }}
                      >
                        {fmtInt(row.ref_mismatches)}
                      </td>
                      <td
                        style={{
                          ...TD,
                          textAlign: "right",
                          color:
                            (row.critical_warnings ?? 0) > 0
                              ? "#b91c1c"
                              : "#374151",
                        }}
                      >
                        {fmtInt(row.critical_warnings)}
                      </td>
                      <td style={{ ...TD, textAlign: "right" }}>
                        {fmtInt(row.tense_mismatches)}
                      </td>
                      <td style={{ ...TD, textAlign: "right" }}>
                        {fmtPct(row.mismatch_rate)}
                      </td>
                      <td style={{ ...TD, textAlign: "right" }}>
                        {fmtInt(row.evidence_count)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
