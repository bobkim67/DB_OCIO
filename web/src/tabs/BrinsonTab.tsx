import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useBrinson } from "../hooks/useBrinson";
import { useFunds } from "../hooks/useFunds";
import MetaBadge from "../components/common/MetaBadge";
import BrinsonWaterfall from "../components/charts/BrinsonWaterfall";
import LoadingBar from "../components/common/LoadingBar";
import type {
  BrinsonAssetRowDTO,
  BrinsonMappingMethod,
  BrinsonSecContribDTO,
} from "../api/endpoints";

interface Props {
  fundCode: string;
}

const MAPPING_METHODS: BrinsonMappingMethod[] = ["방법1", "방법2", "방법3", "방법4"];
const FUND_DEFAULT_MAPPING_METHOD: Record<string, BrinsonMappingMethod> = {
  "4JM12": "방법4",
};

const ROW_ORDER = [
  "주식", "채권", "국내주식", "국내채권", "해외주식", "해외채권",
  "대체", "대체투자", "FX", "모펀드", "기타", "유동성", "유동성및기타",
];
const ROW_ORDER_MAP = new Map(ROW_ORDER.map((c, i) => [c, i]));

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(digits)}%`;
}
function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toFixed(digits);
}
// 부호 없이 % 만 붙임 (비중 등).
function fmtWeight(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}
function ytdStartFor(inception: string | null | undefined): string {
  const today = new Date();
  const year = today.getFullYear();
  const ytd = `${year - 1}-12-31`;
  if (!inception) return ytd;
  const norm = inception.includes("-")
    ? inception
    : `${inception.slice(0, 4)}-${inception.slice(4, 6)}-${inception.slice(6, 8)}`;
  return norm > ytd ? norm : ytd;
}
function yesterday(): string {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

// 종목표 정렬 키
type SecSortKey = keyof Pick<
  BrinsonSecContribDTO,
  "asset_class" | "item_nm" | "weight_pct" | "return_pct" | "contrib_pct"
>;

export default function BrinsonTab({ fundCode }: Props) {
  const { data: fundsData } = useFunds();
  const fundMeta = fundsData?.data.find((f) => f.code === fundCode);
  const inception = fundMeta?.inception ?? null;

  const defaultStart = useMemo(() => ytdStartFor(inception), [inception]);
  const defaultEnd = useMemo(() => yesterday(), []);
  const defaultMethod = FUND_DEFAULT_MAPPING_METHOD[fundCode] ?? "방법3";

  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(defaultEnd);
  const [method, setMethod] = useState<BrinsonMappingMethod>(defaultMethod);
  const [fxSplit, setFxSplit] = useState(true);

  // 종목표 정렬 상태
  const [secSortKey, setSecSortKey] = useState<SecSortKey>("contrib_pct");
  const [secSortDir, setSecSortDir] = useState<"asc" | "desc">("desc");

  useEffect(() => {
    setStartDate(ytdStartFor(inception));
    setEndDate(yesterday());
    setMethod(FUND_DEFAULT_MAPPING_METHOD[fundCode] ?? "방법3");
  }, [fundCode, inception]);

  const { data, isLoading, error, isFetching } = useBrinson({
    code: fundCode,
    startDate,
    endDate,
    mappingMethod: method,
    paMethod: "8", // 8분류 고정 (사용자 요구사항 1)
    fxSplit,
  });

  if (isLoading) return <LoadingBar label="loading brinson... (≈15s on first call)" />;
  if (error || !data) {
    return <div style={{ color: "#dc2626" }}>failed to load brinson</div>;
  }

  const isFallback = data.meta.is_fallback;

  // 자산군별 표 데이터 (정렬 + BM기여 + 초과기여 계산)
  const sortedAssetRows: BrinsonAssetRowDTO[] = [...data.asset_rows].sort((a, b) => {
    const ai = ROW_ORDER_MAP.get(a.asset_class) ?? 99;
    const bi = ROW_ORDER_MAP.get(b.asset_class) ?? 99;
    return ai - bi;
  });
  // BM 기여수익률 = bm_weight × bm_return / 100 (자산군 단순 분해)
  // 초과기여 = Brinson 분해 합 (Allocation + Selection + Cross)
  // → 자산군별 합산이 정확히 total_excess 와 일치 (Brinson 항등식).
  // (단순 차 contrib_return - bm_contrib 는 시간기반 누적 보정 미반영으로
  //  total_excess 와 합이 맞지 않아 사용자 혼선이 발생하므로 채택하지 않음.)
  const enrichedRows = sortedAssetRows.map((r) => {
    const bm_contrib = (r.bm_weight * r.bm_return) / 100;
    const excess_contrib = r.alloc_effect + r.select_effect + r.cross_effect;
    return { ...r, bm_contrib, excess_contrib };
  });
  const sumApContrib = enrichedRows.reduce((s, r) => s + r.contrib_return, 0);
  const sumBmContrib = enrichedRows.reduce((s, r) => s + r.bm_contrib, 0);
  const sumExcessContrib = enrichedRows.reduce((s, r) => s + r.excess_contrib, 0);

  // 종목표 정렬
  const sortedSec: BrinsonSecContribDTO[] = [...data.sec_contrib].sort((a, b) => {
    const av = a[secSortKey];
    const bv = b[secSortKey];
    let cmp: number;
    if (typeof av === "number" && typeof bv === "number") cmp = av - bv;
    else cmp = String(av).localeCompare(String(bv));
    return secSortDir === "asc" ? cmp : -cmp;
  });

  const onSecSort = (k: SecSortKey) => {
    if (secSortKey === k) {
      setSecSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSecSortKey(k);
      setSecSortDir(typeof data.sec_contrib[0]?.[k] === "number" ? "desc" : "asc");
    }
  };
  const sortGlyph = (k: SecSortKey) =>
    secSortKey === k ? (secSortDir === "asc" ? " ▲" : " ▼") : "";

  return (
    <section>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ fontSize: 16, margin: 0 }}>
          {data.fund_name}{" "}
          <span style={{ color: "#6b7280" }}>({data.fund_code})</span>
        </h2>
        <MetaBadge meta={data.meta} />
        {isFetching && (
          <span style={{ fontSize: 11, color: "#6b7280" }}>refreshing…</span>
        )}
      </div>

      {/* 컨트롤 (자산군 8분류 dropdown 제거) */}
      <div
        style={{
          display: "flex",
          gap: 12,
          marginBottom: 16,
          flexWrap: "wrap",
          alignItems: "center",
          padding: "10px 12px",
          background: "#f9fafb",
          border: "1px solid #e5e7eb",
          borderRadius: 6,
        }}
      >
        <label style={lbl}>
          시작
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            style={inp}
          />
        </label>
        <label style={lbl}>
          종료
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            style={inp}
          />
        </label>
        <label style={lbl}>
          분류
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as BrinsonMappingMethod)}
            style={inp}
            title={
              "방법1: 주식/채권/대체/FX/유동성\n방법2: 주식/채권/FX/유동성 (대체→주식)\n방법3: 국내/해외 분리 + 대체\n방법4: 국내/해외 분리 (대체→해외주식)"
            }
          >
            {MAPPING_METHODS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <label style={{ ...lbl, flexDirection: "row", gap: 6, alignItems: "center" }}>
          <input
            type="checkbox"
            checked={fxSplit}
            onChange={(e) => setFxSplit(e.target.checked)}
          />
          FX 분리
        </label>
      </div>

      {/* 합계 카드 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 8,
          marginBottom: 16,
        }}
      >
        {[
          { label: "AP 수익률", value: fmtPct(data.period_ap_return), color: "#2563eb" },
          { label: "BM 수익률", value: fmtPct(data.period_bm_return), color: "#dc2626" },
          {
            label: "초과수익률",
            value: fmtPct(data.total_excess),
            color: data.total_excess >= 0 ? "#16a34a" : "#b91c1c",
          },
          {
            label: "Alloc / Select / Cross",
            value: `${fmtNum(data.total_alloc)} / ${fmtNum(data.total_select)} / ${fmtNum(data.total_cross)}`,
            color: "#374151",
          },
        ].map((c) => (
          <div
            key={c.label}
            style={{
              padding: "10px 12px",
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderRadius: 6,
            }}
          >
            <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>
              {c.label}
            </div>
            <div
              style={{
                fontSize: 18,
                fontWeight: 600,
                color: c.color,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {c.value}
            </div>
          </div>
        ))}
      </div>

      {isFallback && (
        <div
          style={{
            padding: "8px 10px",
            background: "#fef3c7",
            border: "1px solid #fde68a",
            borderRadius: 6,
            fontSize: 12,
            marginBottom: 16,
            color: "#92400e",
          }}
        >
          ⚠️ Brinson 계산 실패 — fallback. {data.meta.warnings.join(" / ")}
        </div>
      )}

      {/* 표 1: 자산군별 기여수익률 (BM기여 + 초과기여 추가) */}
      <div style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: 14, margin: "4px 0 8px" }}>자산군별 기여수익률</h3>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 13,
          }}
        >
          <thead>
            <tr style={{ background: "#f9fafb" }}>
              <th style={th}>자산군</th>
              <th style={thr}>AP비중</th>
              <th style={thr}>BM비중</th>
              <th style={thr}>AP수익률</th>
              <th style={thr}>BM수익률</th>
              <th style={thr}>AP기여</th>
              <th style={thr}>BM기여</th>
              <th style={thr}>초과기여</th>
            </tr>
          </thead>
          <tbody>
            {enrichedRows.map((r) => (
              <tr key={r.asset_class}>
                <td style={td}>{r.asset_class}</td>
                <td style={tdr}>{fmtWeight(r.ap_weight, 1)}</td>
                <td style={tdr}>{fmtWeight(r.bm_weight, 1)}</td>
                <td style={tdr}>{fmtPct(r.ap_return)}</td>
                <td style={tdr}>{fmtPct(r.bm_return)}</td>
                <td
                  style={{
                    ...tdr,
                    fontWeight: 600,
                    color: r.contrib_return < 0 ? "#b91c1c" : "#16a34a",
                  }}
                >
                  {fmtPct(r.contrib_return)}
                </td>
                <td style={tdr}>{fmtPct(r.bm_contrib)}</td>
                <td
                  style={{
                    ...tdr,
                    fontWeight: 600,
                    color: r.excess_contrib < 0 ? "#b91c1c" : "#16a34a",
                  }}
                >
                  {fmtPct(r.excess_contrib)}
                </td>
              </tr>
            ))}
            <tr style={{ background: "#f3f4f6", fontWeight: 600 }}>
              <td style={td}>합계</td>
              <td style={tdr}>—</td>
              <td style={tdr}>—</td>
              <td style={tdr}>—</td>
              <td style={tdr}>—</td>
              <td style={tdr}>{fmtPct(sumApContrib)}</td>
              <td style={tdr}>{fmtPct(sumBmContrib)}</td>
              <td style={tdr}>{fmtPct(sumExcessContrib)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* 표 2: Brinson 분석 (자산군별 Alloc/Select/Cross/자산군별 합계) + 워터폴 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(360px, 1fr) minmax(360px, 1fr)",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <div>
          <h3 style={{ fontSize: 14, margin: "4px 0 8px" }}>
            Brinson 분석 (Allocation / Selection / Cross)
          </h3>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
            }}
          >
            <thead>
              <tr style={{ background: "#f9fafb" }}>
                <th style={th}>자산군</th>
                <th style={thr}>Allocation</th>
                <th style={thr}>Selection</th>
                <th style={thr}>Cross</th>
                <th style={thr}>자산군 별</th>
              </tr>
            </thead>
            <tbody>
              {enrichedRows.map((r) => {
                const rowSum = r.alloc_effect + r.select_effect + r.cross_effect;
                return (
                  <tr key={r.asset_class}>
                    <td style={td}>{r.asset_class}</td>
                    <td style={tdr}>{fmtPct(r.alloc_effect, 3)}</td>
                    <td style={tdr}>{fmtPct(r.select_effect, 3)}</td>
                    <td style={tdr}>{fmtPct(r.cross_effect, 3)}</td>
                    <td
                      style={{
                        ...tdr,
                        fontWeight: 600,
                        color: rowSum < 0 ? "#b91c1c" : "#16a34a",
                      }}
                    >
                      {fmtPct(rowSum, 3)}
                    </td>
                  </tr>
                );
              })}
              <tr style={{ background: "#f3f4f6", fontWeight: 600 }}>
                <td style={td}>요인 합계</td>
                <td style={tdr}>{fmtPct(data.total_alloc, 3)}</td>
                <td style={tdr}>{fmtPct(data.total_select, 3)}</td>
                <td style={tdr}>{fmtPct(data.total_cross, 3)}</td>
                <td style={tdr}>{fmtPct(data.total_excess)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <BrinsonWaterfall
          alloc={data.total_alloc}
          select={data.total_select}
          cross={data.total_cross}
          excess={data.total_excess}
        />
      </div>

      {/* 종목별 기여수익률 (전체 종목 + 비중 + 정렬, 스크롤 X) */}
      <div>
        <h3 style={{ fontSize: 14, margin: "4px 0 8px" }}>종목별 기여수익률</h3>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 13,
          }}
        >
          <thead>
            <tr style={{ background: "#f9fafb" }}>
              <th style={{ ...th, ...thSort }} onClick={() => onSecSort("asset_class")}>
                자산군{sortGlyph("asset_class")}
              </th>
              <th style={{ ...th, ...thSort }} onClick={() => onSecSort("item_nm")}>
                종목명{sortGlyph("item_nm")}
              </th>
              <th style={{ ...thr, ...thSort }} onClick={() => onSecSort("weight_pct")}>
                비중{sortGlyph("weight_pct")}
              </th>
              <th style={{ ...thr, ...thSort }} onClick={() => onSecSort("return_pct")}>
                수익률{sortGlyph("return_pct")}
              </th>
              <th style={{ ...thr, ...thSort }} onClick={() => onSecSort("contrib_pct")}>
                기여수익률{sortGlyph("contrib_pct")}
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedSec.map((s, i) => (
              <tr key={`${s.item_nm}-${i}`}>
                <td style={td}>{s.asset_class}</td>
                <td style={td}>{s.item_nm}</td>
                <td style={tdr}>{fmtWeight(s.weight_pct, 2)}</td>
                <td
                  style={{
                    ...tdr,
                    color: s.return_pct < 0 ? "#b91c1c" : "#16a34a",
                  }}
                >
                  {fmtPct(s.return_pct)}
                </td>
                <td
                  style={{
                    ...tdr,
                    color: s.contrib_pct < 0 ? "#b91c1c" : "#16a34a",
                    fontWeight: 600,
                  }}
                >
                  {fmtPct(s.contrib_pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

const lbl: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  fontSize: 11,
  color: "#374151",
  gap: 4,
};
const inp: CSSProperties = {
  fontSize: 13,
  padding: "4px 6px",
  border: "1px solid #d1d5db",
  borderRadius: 4,
};
const th: CSSProperties = {
  padding: "6px 8px",
  borderBottom: "1px solid #e5e7eb",
  textAlign: "left",
};
const thr: CSSProperties = { ...th, textAlign: "right" };
const thSort: CSSProperties = {
  cursor: "pointer",
  userSelect: "none",
};
const td: CSSProperties = {
  padding: "5px 8px",
  borderBottom: "1px solid #f3f4f6",
};
const tdr: CSSProperties = {
  ...td,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
};
