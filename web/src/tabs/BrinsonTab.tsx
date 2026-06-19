import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
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

  // 입력(draft) 상태 — 사용자가 컨트롤을 만질 때 바뀜
  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(defaultEnd);
  const [method, setMethod] = useState<BrinsonMappingMethod>(defaultMethod);
  const [fxSplit, setFxSplit] = useState(true);
  // 표0 펼치기: 기본=자산군 비중만, 펼치면 AP 종목별 노출
  const [tbl0Expanded, setTbl0Expanded] = useState(false);

  // 적용(applied) 상태 — 실제 조회를 구동. "조회" 버튼을 눌러야 draft → applied 반영.
  const [applied, setApplied] = useState({
    startDate: defaultStart,
    endDate: defaultEnd,
    method: defaultMethod,
    fxSplit: true,
  });

  // 종목표 정렬 상태
  const [secSortKey, setSecSortKey] = useState<SecSortKey>("contrib_pct");
  const [secSortDir, setSecSortDir] = useState<"asc" | "desc">("desc");

  // 펀드(또는 설정일) 변경 시에는 draft·applied 모두 기본값으로 리셋 → 자동 조회.
  useEffect(() => {
    const s = ytdStartFor(inception);
    const e = yesterday();
    const m = FUND_DEFAULT_MAPPING_METHOD[fundCode] ?? "방법3";
    setStartDate(s);
    setEndDate(e);
    setMethod(m);
    setFxSplit(true);
    setApplied({ startDate: s, endDate: e, method: m, fxSplit: true });
  }, [fundCode, inception]);

  // draft 가 applied 와 다르면 "조회" 대기 상태.
  const isDirty =
    startDate !== applied.startDate ||
    endDate !== applied.endDate ||
    method !== applied.method ||
    fxSplit !== applied.fxSplit;

  const onApply = () =>
    setApplied({ startDate, endDate, method, fxSplit });

  const { data, isLoading, error, isFetching } = useBrinson({
    code: fundCode,
    startDate: applied.startDate,
    endDate: applied.endDate,
    mappingMethod: applied.method,
    paMethod: "8", // 8분류 고정 (사용자 요구사항 1)
    fxSplit: applied.fxSplit,
  });

  if (isLoading) return <LoadingBar label="Brinson 계산 중… (최대 ~1분)" />;
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
  // BM 기여수익률 = 백엔드 경로의존 분해(row.bm_contrib) → 합 = period_bm_return (정확).
  //   (기존 bm_weight×bm_return/100 산술 분해는 복리/교차항만큼 합이 안 맞아 폐기)
  // 초과기여 = Brinson 분해 합 (Allocation + Selection + Cross) → 합 = total_excess.
  const enrichedRows = sortedAssetRows.map((r) => {
    const excess_contrib = r.alloc_effect + r.select_effect + r.cross_effect;
    return { ...r, excess_contrib };
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
          <span style={{ fontSize: 11, color: "#2563eb" }}>● 재계산 중…</span>
        )}
      </div>
      {isFetching && (
        <div style={{ marginTop: -8, marginBottom: 8 }}>
          <LoadingBar label="재계산 중… (날짜/조건 변경 — 캐시 미스 시 최대 ~1분)" height={4} />
        </div>
      )}

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
        <button
          type="button"
          onClick={onApply}
          disabled={!isDirty || isFetching}
          style={{
            ...btn,
            opacity: !isDirty || isFetching ? 0.5 : 1,
            cursor: !isDirty || isFetching ? "default" : "pointer",
          }}
        >
          {isFetching ? "조회 중…" : "조회"}
        </button>
        {isDirty && !isFetching && (
          <span style={{ fontSize: 11, color: "#b45309" }}>
            변경됨 — 조회를 눌러 갱신
          </span>
        )}
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

      {/* 표 0: SAA(BM) 구성 vs AP 실제 — 자산군 비교(기본) + 펼치기 시 AP 종목 (FX 제외) */}
      {data.bm_source !== "none" && (() => {
        const isBM = data.bm_source === "BM";
        // BM '유동성'(KAP MMI Call 등)을 AP와 동일하게 '유동성및기타'로 정규화 → 같은 블록으로 묶음
        const normCls = (c: string) => (c === "유동성" ? "유동성및기타" : c);
        // 자산군별 BM 지수(BM=지수명, SAA="—") + 비중
        const saaByClass = new Map<string, { label: string; weight: number }[]>();
        for (const c of data.bm_components) {
          if (c.asset_class === "FX") continue;
          const g = normCls(c.asset_class);
          const arr = saaByClass.get(g) ?? [];
          arr.push({ label: isBM ? c.name : "—", weight: c.weight });
          saaByClass.set(g, arr);
        }
        // 자산군별 AP 보유종목 (비중 내림차순)
        const apByClass = new Map<string, { label: string; weight: number }[]>();
        for (const s of data.sec_contrib) {
          if (s.asset_class === "FX") continue;
          const g = normCls(s.asset_class);
          const arr = apByClass.get(g) ?? [];
          arr.push({ label: s.item_nm, weight: s.weight_pct });
          apByClass.set(g, arr);
        }
        for (const arr of apByClass.values()) arr.sort((a, b) => b.weight - a.weight);
        // 자산군 소계는 asset_rows(정확값) 기준으로 조회 (반올림 누적 방지)
        const subByClass = new Map(enrichedRows.map((r) => [r.asset_class, r]));
        // 자산군 합집합(FX 제외) → ROW_ORDER 순
        const classes = [...new Set([...saaByClass.keys(), ...apByClass.keys()])]
          .filter((g) => g !== "FX")
          .sort((a, b) => (ROW_ORDER_MAP.get(a) ?? 99) - (ROW_ORDER_MAP.get(b) ?? 99));

        return (
          <div style={{ marginBottom: 16 }}>
            <h3
              style={{
                fontSize: 14,
                margin: "4px 0 8px",
                display: "flex",
                alignItems: "center",
                gap: 10,
              }}
            >
              {isBM ? "벤치마크(BM) 구성" : "전략적 자산배분(SAA) 구성"}
              <span style={{ fontSize: 11, color: "#6b7280", fontWeight: 400 }}>
                목표 셋팅 vs AP 실제 (FX 제외)
              </span>
              <button
                type="button"
                onClick={() => setTbl0Expanded((v) => !v)}
                style={{
                  fontSize: 11,
                  fontWeight: 500,
                  padding: "2px 10px",
                  border: "1px solid #d1d5db",
                  borderRadius: 4,
                  background: "#fff",
                  cursor: "pointer",
                  color: "#374151",
                }}
              >
                {tbl0Expanded ? "▲ 접기" : "▼ 종목 펼치기"}
              </button>
            </h3>
            <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#f9fafb" }}>
                  <th style={th}>자산군</th>
                  <th style={th}>{isBM ? "BM 지수" : "SAA"}</th>
                  <th style={thr}>{isBM ? "BM비중" : "SAA비중"}</th>
                  <th style={tdGap} />
                  <th style={th}>AP</th>
                  <th style={thr}>AP비중</th>
                  <th style={thr}>차이</th>
                </tr>
              </thead>
              <tbody>
                {classes.flatMap((g) => {
                  const saa = saaByClass.get(g) ?? [];
                  const ap = apByClass.get(g) ?? [];
                  const sub = subByClass.get(g);
                  const apSub = sub?.ap_weight ?? ap.reduce((s, x) => s + x.weight, 0);
                  const bmSub = sub?.bm_weight ?? saa.reduce((s, x) => s + x.weight, 0);
                  const diff = apSub - bmSub;
                  // BM은 자산군당 한 줄 — 지수명 합치고 비중은 소계 표시
                  const bmLabel = saa.map((s) => s.label).filter((l) => l && l !== "—").join(", ");
                  const rows: ReactNode[] = [];
                  // 자산군 행 (항상 표시): BM 지수/비중 + AP 자산군 비중(±%p vs BM)
                  rows.push(
                    <tr
                      key={`${g}-cls`}
                      style={{ borderTop: "2px solid #e5e7eb", background: "#fcfcfd" }}
                    >
                      <td style={{ ...td, fontWeight: 600 }}>{g}</td>
                      <td style={{ ...td, color: "#6b7280" }}>{bmLabel}</td>
                      <td style={{ ...tdr, fontWeight: 600 }}>{fmtWeight(bmSub, 1)}</td>
                      <td style={tdGap} />
                      <td style={{ ...td, fontWeight: 600 }}>{g}</td>
                      <td style={{ ...tdr, fontWeight: 600 }}>{fmtWeight(apSub, 1)}</td>
                      <td
                        style={{
                          ...tdr,
                          fontWeight: 600,
                          color: diff >= 0 ? "#16a34a" : "#b91c1c",
                        }}
                      >
                        {diff >= 0 ? "+" : ""}
                        {diff.toFixed(1)}%p
                      </td>
                    </tr>,
                  );
                  // 펼침 시 AP 종목 행 (BM 컬럼 빈칸)
                  if (tbl0Expanded) {
                    for (let i = 0; i < ap.length; i++) {
                      rows.push(
                        <tr key={`${g}-ap-${i}`}>
                          <td style={td} />
                          <td style={td} />
                          <td style={td} />
                          <td style={tdGap} />
                          <td style={{ ...td, paddingLeft: 18, color: "#374151" }}>
                            {ap[i].label}
                          </td>
                          <td style={tdr}>{fmtWeight(ap[i].weight, 1)}</td>
                          <td style={tdr} />
                        </tr>,
                      );
                    }
                  }
                  return rows;
                })}
              </tbody>
            </table>
            {!isBM && (
              <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 4 }}>
                ※ BM 미설정 펀드 — SAA(MP) 목표비중으로 비중만 비교 (수익률/기여 분해는 미제공).
              </div>
            )}
          </div>
        );
      })()}

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
              <th style={thr}>AP비중 (vs BM)</th>
              <th style={thr}>BM비중</th>
              <th style={thr}>AP기여</th>
              <th style={thr}>BM기여</th>
              <th style={thr}>초과기여</th>
            </tr>
          </thead>
          <tbody>
            {enrichedRows.map((r) => (
              <tr key={r.asset_class}>
                <td style={td}>{r.asset_class}</td>
                <td style={tdr}>
                  {fmtWeight(r.ap_weight, 1)}
                  <span style={{ color: "#9ca3af", fontSize: 11 }}>
                    {" "}({r.ap_weight - r.bm_weight >= 0 ? "+" : ""}
                    {(r.ap_weight - r.bm_weight).toFixed(1)}%p)
                  </span>
                </td>
                <td style={tdr}>{fmtWeight(r.bm_weight, 1)}</td>
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
const btn: CSSProperties = {
  alignSelf: "flex-end",
  fontSize: 13,
  fontWeight: 600,
  padding: "6px 16px",
  color: "#fff",
  background: "#2563eb",
  border: "1px solid #2563eb",
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
// BM 블록 ↔ AP 블록 사이 시각 분리용 좁은 갭 컬럼
const tdGap: CSSProperties = { width: 16, padding: 0, borderBottom: "none" };
