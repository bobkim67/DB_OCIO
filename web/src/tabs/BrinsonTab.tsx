import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { useBrinson } from "../hooks/useBrinson";
import { useFunds } from "../hooks/useFunds";
import MetaBadge from "../components/common/MetaBadge";
import BrinsonWaterfall from "../components/charts/BrinsonWaterfall";
import BrinsonTrendPanel from "../components/charts/BrinsonTrendPanel";
import BrinsonMetricsPanel from "../components/charts/BrinsonMetricsPanel";
import BrinsonFactorTrendChart from "../components/charts/BrinsonFactorTrendChart";
import BrinsonProgressBar from "../components/common/BrinsonProgressBar";
import type {
  BrinsonAssetRowDTO,
  BrinsonMappingMethod,
  BrinsonSecContribDTO,
} from "../api/endpoints";

interface Props {
  fundCode: string;
}

// 드롭다운은 '방법N' 대신 자산군 구성으로 표기 (구성 개수 오름차순). value 는 방법N 유지.
// (FX·유동성은 모든 방법 공통이라 라벨에서 생략 — 코어 분류만 노출)
const MAPPING_METHODS: BrinsonMappingMethod[] = ["방법2", "방법1", "방법4", "방법3"];
const METHOD_LABEL: Record<BrinsonMappingMethod, string> = {
  "방법2": "주식 | 채권",
  "방법1": "주식 | 채권 | 대체",
  "방법4": "국내주식 | 국내채권 | 해외주식 | 해외채권",
  "방법3": "국내주식 | 국내채권 | 해외주식 | 해외채권 | 대체",
};
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

// 자동 진행 날짜 입력 — 연(4)·월(2) 채우면 다음 칸으로 포커스 이동. 값=YYYY-MM-DD.
function DateField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [y = "", m = "", d = ""] = (value || "").split("-");
  const mRef = useRef<HTMLInputElement>(null);
  const dRef = useRef<HTMLInputElement>(null);
  const seg: CSSProperties = {
    border: "none", outline: "none", textAlign: "center", fontSize: 13,
    fontVariantNumeric: "tabular-nums", padding: 0, background: "transparent",
  };
  const emit = (yy: string, mm: string, dd: string) => onChange(`${yy}-${mm}-${dd}`);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 2, border: "1px solid #d1d5db", borderRadius: 4, padding: "4px 6px", background: "#fff" }}>
      <input aria-label="연" inputMode="numeric" placeholder="YYYY" maxLength={4} value={y}
        onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 4); emit(v, m, d); if (v.length === 4) mRef.current?.focus(); }}
        style={{ ...seg, width: 38 }} />
      <span style={{ color: "#9ca3af" }}>-</span>
      <input ref={mRef} aria-label="월" inputMode="numeric" placeholder="MM" maxLength={2} value={m}
        onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 2); emit(y, v, d); if (v.length === 2) dRef.current?.focus(); }}
        style={{ ...seg, width: 22 }} />
      <span style={{ color: "#9ca3af" }}>-</span>
      <input ref={dRef} aria-label="일" inputMode="numeric" placeholder="DD" maxLength={2} value={d}
        onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 2); emit(y, m, v); }}
        style={{ ...seg, width: 22 }} />
    </span>
  );
}

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
  // FX 포함(false)이 기본 — 환효과를 해외 자산 수익률에 접어넣어 별도 FX 행 없이 합=AP.
  const [fxSplit, setFxSplit] = useState(false);
  // 벤치마크 소스(등록 SAA/proxy) × 비중방식(고정=constant-mix / drift=buy-and-hold)
  const [saaSource, setSaaSource] = useState<"auto" | "proxy">("auto");
  const [weightMode, setWeightMode] = useState<"fixed" | "drift">("fixed");
  const saaMode = (
    (saaSource === "proxy" ? "proxy" : "auto") + (weightMode === "drift" ? "_drift" : "")
  ) as "auto" | "auto_drift" | "proxy" | "proxy_drift";
  // 펼치기(공통): 벤치마크 구성 표(표0)의 토글 하나로 표0·표1 둘 다 종목 펼침/접힘.
  const [tbl0Expanded, setTbl0Expanded] = useState(false);
  // 표1 지표: 기여(=배분비중×수익률, 합=포트수익률) / Normalized(=자산군 수익률, 배분비중 미반영)
  const [tbl1Metric, setTbl1Metric] = useState<"contrib" | "norm">("contrib");

  // 적용(applied) 상태 — 실제 조회를 구동. "조회" 버튼을 눌러야 draft → applied 반영.
  const [applied, setApplied] = useState({
    startDate: defaultStart,
    endDate: defaultEnd,
    method: defaultMethod,
    fxSplit: false,
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
    setFxSplit(false);
    setSaaSource("auto");
    setWeightMode("fixed");
    setApplied({ startDate: s, endDate: e, method: m, fxSplit: false });
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
    saaMode,
  });

  if (isLoading) return <BrinsonProgressBar label="Brinson 계산 중" />;
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

  // 표1 펼치기 — 표0(BM/SAA 구성)과 동일 행구조(같은 AP종목·정렬·FX제외)로 BM티커/AP종목 별도 컬럼.
  const normCls1 = (c: string) => (c === "유동성" ? "유동성및기타" : c);
  // AP 종목 (FX 제외, 비중 내림차순 = 표0 동일 정렬) — 표0과 자산군당 행수 일치
  // contrib=기여수익률, ret=종목 자체 수익률(Normalized 모드 표시용)
  const apSecByClass1 = new Map<
    string,
    { item_nm: string; weight: number; contrib: number; ret: number }[]
  >();
  for (const s of data.sec_contrib) {
    if (s.asset_class === "FX") continue;
    const g = normCls1(s.asset_class);
    const arr = apSecByClass1.get(g) ?? [];
    arr.push({ item_nm: s.item_nm, weight: s.weight_pct, contrib: s.contrib_pct, ret: s.return_pct });
    apSecByClass1.set(g, arr);
  }
  for (const arr of apSecByClass1.values()) arr.sort((a, b) => b.weight - a.weight);
  // 자산군별 BM 지수명(조인) — name===자산군명(MP 목표비중뿐)은 제외, FX 제외
  const bmLabelByClass = new Map<string, string>();
  for (const c of data.bm_components) {
    if (c.asset_class === "FX") continue;
    if (!c.name || c.name === c.asset_class) continue;
    const g = normCls1(c.asset_class);
    const prev = bmLabelByClass.get(g);
    bmLabelByClass.set(g, prev ? `${prev}, ${c.name}` : c.name);
  }

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
          <BrinsonProgressBar label="재계산 중 (조건 변경)" height={4} />
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
          <DateField value={startDate} onChange={setStartDate} />
        </label>
        <label style={lbl}>
          종료
          <DateField value={endDate} onChange={setEndDate} />
        </label>
        <label style={lbl}>
          분류
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as BrinsonMappingMethod)}
            style={inp}
            title={"자산군 분류 기준 (FX·유동성은 모든 방식 공통)"}
          >
            {MAPPING_METHODS.map((m) => (
              <option key={m} value={m}>
                {METHOD_LABEL[m]}
              </option>
            ))}
          </select>
        </label>
        <label style={lbl}>
          FX
          <select
            value={fxSplit ? "split" : "incl"}
            onChange={(e) => setFxSplit(e.target.value === "split")}
            style={inp}
            title={
              "FX 포함: 환효과를 해외주식/해외채권 수익률에 접어넣음 (별도 FX 자산군 없음)\nFX 분리: 환효과를 별도 FX 자산군으로 분리"
            }
          >
            <option value="incl">FX 포함</option>
            <option value="split">FX 분리</option>
          </select>
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
        {/* 소스: 등록 SAA ↔ proxy (SAA 펀드만). 비중: 고정(constant-mix) ↔ drift(buy-and-hold, 전체) */}
        {data.bm_source !== "BM" && (
          <label style={lbl}>
            소스
            <select
              value={saaSource}
              onChange={(e) => setSaaSource(e.target.value as "auto" | "proxy")}
              disabled={isFetching}
              style={inp}
              title={
                "등록 SAA: 등록된 SAA 인덱스\nproxy: 안전자산(채권 ex-HY)→KIS 종합채권 / 나머지→MSCI ACWI"
              }
            >
              <option value="auto">등록 SAA</option>
              <option value="proxy">proxy (MSCI ACWI · KIS 종합채권)</option>
            </select>
          </label>
        )}
        <label style={lbl}>
          비중
          <select
            value={weightMode}
            onChange={(e) => setWeightMode(e.target.value as "fixed" | "drift")}
            disabled={isFetching}
            style={inp}
            title={
              "고정(constant-mix): 매일 목표비중 리밸런싱\ndrift(buy-and-hold): 리밸 target에서 인덱스 수익률대로 비중 표류"
            }
          >
            <option value="fixed">고정</option>
            <option value="drift">drift</option>
          </select>
        </label>
      </div>

      {/* 합계 카드 */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
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

      {/* ④ 위험조정 성과지표 (연율화수익·변동성·MDD + TE·IR) */}
      <div style={{ marginBottom: 16, maxWidth: 460 }}>
        <BrinsonMetricsPanel daily={data.daily_brinson} hasBm={data.bm_source !== "none"} />
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

      {/* 표0(BM/SAA 구성) + 표1(자산군별 기여수익률) side-by-side */}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap", marginBottom: 16 }}>
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
          // BM=지수명. SAA=등록/proxy 인덱스명(name). MP 목표비중 SAA는 name===자산군명이라 "—".
          const idxName = c.name && c.name !== c.asset_class ? c.name : "—";
          arr.push({ label: idxName, weight: c.weight });
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
          <div style={{ flex: "1 1 420px", minWidth: 0 }}>
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
                  <th style={th}>{isBM ? "BM 지수" : "SAA 지수"}</th>
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
                      <td style={td}>{g}</td>
                      <td style={{ ...td, color: "#6b7280" }}>{bmLabel}</td>
                      <td style={tdr}>{fmtWeight(bmSub, 1)}</td>
                      <td style={tdGap} />
                      <td style={td}>{g}</td>
                      <td style={tdr}>{fmtWeight(apSub, 1)}</td>
                      <td
                        style={{
                          ...tdr,
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
              data.bm_components.some((c) => c.name && c.name !== c.asset_class) ? (
                <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 4 }}>
                  ※ SAA 벤치마크(등록 인덱스) 기준 — 수익률·기여 분해 제공.
                </div>
              ) : (
                <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 4 }}>
                  ※ BM 미설정 펀드 — SAA(MP) 목표비중으로 비중만 비교 (수익률/기여 분해는 미제공).
                </div>
              )
            )}
          </div>
        );
      })()}

      {/* 표 1: 자산군별 기여수익률 (BM기여 + 초과기여) — 비중 컬럼 제거, 표0 우측 배치 */}
      <div style={{ flex: "1 1 420px", minWidth: 0 }}>
        <h3
          style={{
            fontSize: 14,
            margin: "4px 0 8px",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          자산군별 {tbl1Metric === "norm" ? "수익률(Normalized)" : "기여수익률"}
          <button
            type="button"
            onClick={() => setTbl0Expanded((v) => !v)}
            style={{
              marginLeft: "auto",
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
        {/* 기여/Normalized 토글 — 테이블 우측 상단 */}
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 6 }}>
          <span
            style={{
              display: "inline-flex",
              border: "1px solid #d1d5db",
              borderRadius: 4,
              overflow: "hidden",
            }}
          >
            {(
              [
                ["contrib", "기여"],
                ["norm", "Normalized"],
              ] as const
            ).map(([m, label]) => (
              <button
                key={m}
                type="button"
                onClick={() => setTbl1Metric(m)}
                title={
                  m === "contrib"
                    ? "기여수익률 = 배분비중 × 자산군수익률 (합 = 포트 수익률)"
                    : "순수 수익률 (편입비중 반영X)"
                }
                style={{
                  fontSize: 11,
                  fontWeight: 500,
                  padding: "2px 10px",
                  border: "none",
                  cursor: "pointer",
                  background: tbl1Metric === m ? "#2563eb" : "#fff",
                  color: tbl1Metric === m ? "#fff" : "#374151",
                }}
              >
                {label}
              </button>
            ))}
          </span>
        </div>
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
              <th style={th}>BM티커</th>
              <th style={thr}>
                BM 수익률({tbl1Metric === "norm" ? "Normalized" : "기여"})
              </th>
              <th style={tdGap} />
              <th style={th}>AP</th>
              <th style={thr}>
                AP 수익률({tbl1Metric === "norm" ? "Normalized" : "기여"})
              </th>
              {tbl1Metric !== "norm" && <th style={thr}>초과기여</th>}
            </tr>
          </thead>
          <tbody>
            {enrichedRows.flatMap((r) => {
              const bmLabel = bmLabelByClass.get(r.asset_class) ?? "";
              const isNorm = tbl1Metric === "norm";
              const bmVal = isNorm ? r.bm_return : r.bm_contrib;
              const apVal = isNorm ? r.ap_return : r.contrib_return;
              const rows: ReactNode[] = [
                <tr
                  key={r.asset_class}
                  style={{ borderTop: "2px solid #e5e7eb", background: "#fcfcfd" }}
                >
                  <td style={td}>{r.asset_class}</td>
                  <td style={{ ...td, color: "#6b7280" }}>{bmLabel}</td>
                  <td style={tdr}>{fmtPct(bmVal)}</td>
                  <td style={tdGap} />
                  <td style={td}>{r.asset_class}</td>
                  <td
                    style={{
                      ...tdr,
                      fontWeight: 600,
                      color: apVal < 0 ? "#b91c1c" : "#16a34a",
                    }}
                  >
                    {fmtPct(apVal)}
                  </td>
                  {!isNorm && (
                    <td
                      style={{
                        ...tdr,
                        fontWeight: 600,
                        color: r.excess_contrib < 0 ? "#b91c1c" : "#16a34a",
                      }}
                    >
                      {fmtPct(r.excess_contrib)}
                    </td>
                  )}
                </tr>,
              ];
              // 펼침 시 AP 종목 행 (BM 컬럼 빈칸) — 표0 과 동일 행수, 표0 토글과 연동
              if (tbl0Expanded) {
                const secs = apSecByClass1.get(r.asset_class) ?? [];
                for (let i = 0; i < secs.length; i++) {
                  const secVal = isNorm ? secs[i].ret : secs[i].contrib;
                  rows.push(
                    <tr key={`${r.asset_class}-sec-${i}`}>
                      <td style={td} />
                      <td style={td} />
                      <td style={td} />
                      <td style={tdGap} />
                      <td style={{ ...td, paddingLeft: 18, color: "#374151" }}>
                        {secs[i].item_nm}
                      </td>
                      <td style={{ ...tdr, color: secVal < 0 ? "#b91c1c" : "#16a34a" }}>
                        {fmtPct(secVal)}
                      </td>
                      {!isNorm && <td style={tdr} />}
                    </tr>,
                  );
                }
                // 잔차 행 — 기여 모드만. (Normalized 는 수익률이라 종목 합산 불가 → 잔차 개념 없음)
                // 기여 모드: 종목합 ≠ 자산군 소계. FX 포함 모드에서 통화 cross-term 등 종목에
                // 귀속 안 되는 분이 소계에 들어가는데, 차이를 명시해 종목합+잔차=소계로 맞춤.
                if (!isNorm) {
                  const secSum = secs.reduce((s, x) => s + x.contrib, 0);
                  const resid = r.contrib_return - secSum;
                  if (Math.abs(resid) >= 0.005) {
                    rows.push(
                      <tr key={`${r.asset_class}-resid`}>
                        <td style={td} />
                        <td style={td} />
                        <td style={td} />
                        <td style={tdGap} />
                        <td
                          style={{
                            ...td,
                            paddingLeft: 18,
                            color: "#6b7280",
                            fontStyle: "italic",
                          }}
                        >
                          기타(잔차)
                        </td>
                        <td
                          style={{ ...tdr, color: resid < 0 ? "#b91c1c" : "#16a34a" }}
                        >
                          {fmtPct(resid)}
                        </td>
                        <td style={tdr} />
                      </tr>,
                    );
                  }
                }
              }
              return rows;
            })}
            {tbl1Metric !== "norm" && (
              <tr style={{ background: "#f3f4f6", fontWeight: 600 }}>
                <td style={td}>합계</td>
                <td style={td} />
                <td style={tdr}>{fmtPct(sumBmContrib)}</td>
                <td style={tdGap} />
                <td style={td} />
                <td style={tdr}>{fmtPct(sumApContrib)}</td>
                <td style={tdr}>{fmtPct(sumExcessContrib)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      </div>

      {/* B4: AP vs BM 추이 (좌=누적수익/누적기여, 우=비중추이/SAA) */}
      <div style={{ marginBottom: 16 }}>
        <BrinsonTrendPanel
          daily={data.daily_brinson}
          dailyClass={data.daily_class ?? []}
          bmSource={data.bm_source}
          bmComponents={data.bm_components ?? []}
        />
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

      {/* ① 요인별 초과수익 누적 추이 (워터폴의 시계열 버전) */}
      {data.bm_source !== "none" && (
        <div style={{ marginBottom: 16 }}>
          <BrinsonFactorTrendChart daily={data.daily_brinson} />
        </div>
      )}

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
