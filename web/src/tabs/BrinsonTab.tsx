import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { api } from "../api/client";
import { useBrinson, useBrinsonPeriods } from "../hooks/useBrinson";
import { useFunds } from "../hooks/useFunds";
import { useOverview } from "../hooks/useOverview";
import { usePeriodReturns } from "../hooks/usePeriodReturns";
import { useTransactions } from "../hooks/useTransactions";
import { computeBrinsonMetrics } from "../lib/brinsonMetrics";
import BrinsonWaterfall from "../components/charts/BrinsonWaterfall";
import BrinsonTrendPanel, { type Mode as TrendMode } from "../components/charts/BrinsonTrendPanel";
import BrinsonMetricsPanel from "../components/charts/BrinsonMetricsPanel";
import BrinsonFactorTrendChart from "../components/charts/BrinsonFactorTrendChart";
import BrinsonProgressBar from "../components/common/BrinsonProgressBar";
import type {
  BrinsonAssetRowDTO,
  BrinsonMappingMethod,
  BrinsonPeriodDTO,
  BrinsonPeriodRowDTO,
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
// 수익률 색 (양수=코랄 up / 음수=스틸블루 dn), 초과 색 (달성=초록 ok / 미달=빨강 bad).
const rc = (v: number) => (v < 0 ? "dn" : "up");
const ec = (v: number) => (v < 0 ? "bad" : "ok");
// 초과기여 색 — 양수=초록 파스텔 / 음수=브라운 파스텔 (2026-07-03 사용자 지정)
const xc = (v: number) => (v < 0 ? "exbr" : "exgr");

// 유동성및기타 개별노출 대상 (편입종목 탭 collapseLiquidity 동일 규칙) —
// 예금·USD Deposit·현금/미수금·환매미지급금만 개별, 나머지(콜론·MMF 등)는 "기타" 합산.
const isLiqKeep = (nm: string) =>
  nm.includes("예금") || nm.toUpperCase().includes("DEPOSIT")
  || nm.includes("미수금") || nm.includes("미지급금");

// 좌(BM)/우(AP) 분리 테이블 행 정렬용 빈 패딩 행 — 자산군별 상세 행수를 좌우 동일하게 맞춤
const padRows = (keyPrefix: string, n: number, cols: number): ReactNode[] =>
  Array.from({ length: n }, (_, i) => (
    <tr key={`${keyPrefix}-pad-${i}`}>
      {Array.from({ length: cols }, (_, j) => <td key={j}>{" "}</td>)}
    </tr>
  ));
// 기간별 수익률 표 컬럼 (period_returns 키 → 라벨). 값은 분수(소수)라 *100.
const PERIOD_COLS: [string, string][] = [
  ["1M", "1M"], ["3M", "3M"], ["6M", "6M"], ["1Y", "1Y"], ["YTD", "YTD"], ["SI", "설정후"],
];
function ytdStartFor(inception: string | null | undefined): string {
  const today = new Date();
  const year = today.getFullYear();
  const ytd = `${year}-01-01`; // base=전년말 (백엔드 start=첫 수익 인식일 규약, 2026-07-06)
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
// 로컬 타임존 기준 YYYY-MM-DD (toISOString UTC 보정 회피)
function fmtLocal(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function monthsAgoStr(n: number): string {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return fmtLocal(d);
}
function startOfMonthStr(): string {
  const d = new Date();
  return fmtLocal(new Date(d.getFullYear(), d.getMonth(), 1));
}
// inception(YYYYMMDD 또는 YYYY-MM-DD) → YYYY-MM-DD. 없으면 이른 날짜.
function inceptionStr(inception: string | null | undefined): string {
  if (!inception) return "2000-01-01";
  return inception.includes("-")
    ? inception
    : `${inception.slice(0, 4)}-${inception.slice(4, 6)}-${inception.slice(6, 8)}`;
}

// 기간 preset (거래내역 탭과 동일 칩 UI). 종료일은 성과분석 규칙대로 어제(custom 제외).
// "custom"은 칩 없이 내부 상태로만 사용 — DateField 수동 편집 시 진입(칩 하이라이트 해제).
type BnPreset = "MTD" | "1M" | "3M" | "6M" | "YTD" | "since" | "custom";
const BN_PRESETS: { key: BnPreset; label: string }[] = [
  { key: "MTD", label: "당월" },
  { key: "1M", label: "1개월" },
  { key: "3M", label: "3개월" },
  { key: "6M", label: "6개월" },
  { key: "YTD", label: "연초이후" },
  { key: "since", label: "설정후" },
];

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
    fontFamily: "inherit", fontVariantNumeric: "tabular-nums", padding: 0,
    background: "transparent", color: "inherit",
  };
  const emit = (yy: string, mm: string, dd: string) => onChange(`${yy}-${mm}-${dd}`);
  // 포커스·클릭 시 해당 칸 전체 선택 → 한 번에 덮어쓰기 (자동진행 .focus() 도 트리거)
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 2, border: "1px solid var(--ace-line-2)", borderRadius: 6, padding: "5px 7px", background: "#fff" }}>
      <input aria-label="연" inputMode="numeric" placeholder="YYYY" maxLength={4} value={y}
        onFocus={(e) => e.currentTarget.select()} onClick={(e) => e.currentTarget.select()}
        onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 4); emit(v, m, d); if (v.length === 4) mRef.current?.focus(); }}
        style={{ ...seg, width: 38 }} />
      <span style={{ color: "#9ca3af" }}>-</span>
      <input ref={mRef} aria-label="월" inputMode="numeric" placeholder="MM" maxLength={2} value={m}
        onFocus={(e) => e.currentTarget.select()} onClick={(e) => e.currentTarget.select()}
        onChange={(e) => { const v = e.target.value.replace(/\D/g, "").slice(0, 2); emit(y, v, d); if (v.length === 2) dRef.current?.focus(); }}
        style={{ ...seg, width: 22 }} />
      <span style={{ color: "#9ca3af" }}>-</span>
      <input ref={dRef} aria-label="일" inputMode="numeric" placeholder="DD" maxLength={2} value={d}
        onFocus={(e) => e.currentTarget.select()} onClick={(e) => e.currentTarget.select()}
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
  // 기간 preset (칩). 기본=연초이후(YTD). custom 은 DateField 수동입력.
  const [preset, setPreset] = useState<BnPreset>("YTD");
  // 펼치기(공통): 벤치마크 구성 표(표0)의 토글 하나로 표0·표1 둘 다 종목 펼침/접힘.
  const [tbl0Expanded, setTbl0Expanded] = useState(false);
  // 표1 지표: 기여(=배분비중×수익률, 합=포트수익률) / Normalized(=자산군 수익률, 배분비중 미반영)
  const [tbl1Metric, setTbl1Metric] = useState<"contrib" | "norm">("contrib");
  // 수익률 분석 패널 모드/선택 자산군 (controlled) — 하단 기간 효과표와 공유.
  const [trendMode, setTrendMode] = useState<TrendMode>("all");
  const [trendSel, setTrendSel] = useState<string>("");
  // 전체 모드에서 기간별 수익률 ↔ 요인효과 테이블 토글.
  const [factorToggle, setFactorToggle] = useState(false);

  // 적용(applied) 상태 — 실제 조회를 구동. "조회" 버튼을 눌러야 draft → applied 반영.
  const [applied, setApplied] = useState({
    startDate: defaultStart,
    endDate: defaultEnd,
    method: defaultMethod,
    fxSplit: false,
  });

  // 기간별 수익률 표(수익률분석 카드 하단) — 조회 종료일(applied.endDate) 앵커 트레일링
  // 수익률 (2026-07-03 사용자 지정: 1M 이 브린슨 조회기간 KPI 와 같은 윈도우로 떨어짐).
  const prq = usePeriodReturns(fundCode, applied.endDate);

  // KPI 우측 스냅샷 카드 (설정액/NAV/기준가, 종료일 기준 + 시작일 대비 변동, 2026-07-07)
  // — Overview nav_series(기준가·순자산) + 거래 cashflows(기간 순설정) 재사용.
  const ovq = useOverview(fundCode);
  const cfq = useTransactions(fundCode, applied.startDate, applied.endDate);
  const kpiSnap = useMemo(() => {
    const series = ovq.data?.nav_series ?? [];
    const at = (d: string) => {
      let last: (typeof series)[number] | null = null;
      for (const p of series) { if (p.date <= d) last = p; else break; }
      return last;
    };
    const s0 = at(applied.startDate);
    const s1 = at(applied.endDate);
    const price0 = s0?.nav ?? null, price1 = s1?.nav ?? null;
    const nast0 = s0?.aum ?? null, nast1 = s1?.aum ?? null;
    let setupNetEok = 0;
    for (const c of cfq.data?.cashflows ?? []) {
      setupNetEok += c.side === "설정" ? c.amount_eok : c.side === "해지" ? -c.amount_eok : 0;
    }
    // 설정액(누적 순설정) 스냅샷 — fund_meta.setup_amount 는 최신 누적(기본 종료일=어제와 일치).
    const setupEnd = ovq.data?.fund_meta?.setup_amount ?? null;
    const setupStart = setupEnd != null ? setupEnd - setupNetEok * 1e8 : null;
    return {
      price0, price1,
      priceD: price0 != null && price1 != null ? price1 - price0 : null,
      pricePct: price0 ? (price1! - price0) / price0 : null,
      nast0, nast1,
      nastD: nast0 != null && nast1 != null ? nast1 - nast0 : null,
      nastPct: nast0 ? (nast1! - nast0) / nast0 : null,
      setupEnd, setupNetEok,
      setupPct: setupStart ? (setupNetEok * 1e8) / setupStart : null,
    };
  }, [ovq.data, cfq.data, applied.startDate, applied.endDate]);

  // 엑셀 스냅샷 내려받기 — 화면 조회조건 그대로 서버에서 xlsx 생성 (방법1 콜드 계산 포함 수십 초).
  const [exporting, setExporting] = useState(false);
  const onExport = async () => {
    setExporting(true);
    try {
      const r = await api.get<Blob>(`/funds/${fundCode}/brinson/export`, {
        params: {
          start_date: applied.startDate, end_date: applied.endDate,
          mapping_method: applied.method, pa_method: "8",
          fx_split: applied.fxSplit, saa_mode: saaMode,
        },
        responseType: "blob", timeout: 300_000,
      });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `성과분석_${fundCode}_${applied.startDate}_${applied.endDate}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      window.alert("엑셀 생성에 실패했습니다. 잠시 후 다시 시도해주세요.");
    } finally {
      setExporting(false);
    }
  };

  // 종목표 정렬 상태
  const [secSortKey, setSecSortKey] = useState<SecSortKey>("contrib_pct");
  const [secSortDir, setSecSortDir] = useState<"asc" | "desc">("desc");

  // 펀드 변경 시: 사용자가 지정한 기간(시작/종료일)은 유지한다 (사용자 지정 2026-07-03).
  // 단 새 펀드 데이터 범위(설정일~어제)를 벗어나면 가장 가까운 가능일로 보정 + 안내 팝업.
  // 펀드 종속 설정(분류방법·FX·SAA 토글)만 기본값으로 리셋. 최초 마운트/메타 로딩 시엔
  // 기존처럼 기본값(연초이후) 세팅.
  const prevFundRef = useRef<string | null>(null);
  const [adjustNote, setAdjustNote] = useState<string | null>(null);
  useEffect(() => {
    const fundChanged = prevFundRef.current !== null && prevFundRef.current !== fundCode;
    prevFundRef.current = fundCode;
    const m = FUND_DEFAULT_MAPPING_METHOD[fundCode] ?? "방법3";
    setMethod(m);
    setFxSplit(false);
    setSaaSource("auto");
    setWeightMode("fixed");
    if (!fundChanged) {
      const s = ytdStartFor(inception);
      const e = yesterday();
      setStartDate(s);
      setEndDate(e);
      setPreset("YTD");
      setApplied({ startDate: s, endDate: e, method: m, fxSplit: false });
      return;
    }
    const inc = inceptionStr(inception);
    const ymax = yesterday();
    let s = startDate;
    let e = endDate;
    const notes: string[] = [];
    if (s < inc) { notes.push(`시작일 ${s} → ${inc}(설정일)`); s = inc; }
    if (e > ymax) { notes.push(`종료일 ${e} → ${ymax}`); e = ymax; }
    if (e <= s) { notes.push(`종료일 ${e} → ${ymax}(시작일 이후로 조정)`); e = ymax; }
    setStartDate(s);
    setEndDate(e);
    if (notes.length) {
      setPreset("custom");
      setAdjustNote(`지정 기간이 ${fundCode} 데이터 범위를 벗어나 조정했습니다 — ${notes.join(", ")}`);
    }
    setApplied({ startDate: s, endDate: e, method: m, fxSplit: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fundCode, inception]);

  // 기간 보정 안내 팝업 자동 소멸 (8초)
  useEffect(() => {
    if (!adjustNote) return;
    const t = setTimeout(() => setAdjustNote(null), 8000);
    return () => clearTimeout(t);
  }, [adjustNote]);

  // draft 가 applied 와 다르면 "조회" 대기 상태.
  const isDirty =
    startDate !== applied.startDate ||
    endDate !== applied.endDate ||
    method !== applied.method ||
    fxSplit !== applied.fxSplit;

  const onApply = () =>
    setApplied({ startDate, endDate, method, fxSplit });

  // preset 칩 클릭 → 시작/종료 자동 설정 + 즉시 조회(applied 갱신). custom 은 DateField 수동.
  const applyPreset = (p: BnPreset) => {
    setPreset(p);
    if (p === "custom") return; // 직접 지정: 현재 DateField 값 유지(조회 버튼으로 적용)
    const e = yesterday();
    let s: string;
    switch (p) {
      case "MTD": s = startOfMonthStr(); break;
      case "1M": s = monthsAgoStr(1); break;
      case "3M": s = monthsAgoStr(3); break;
      case "6M": s = monthsAgoStr(6); break;
      case "YTD": s = ytdStartFor(inception); break;
      case "since": s = inceptionStr(inception); break;
      default: s = startDate;
    }
    setStartDate(s);
    setEndDate(e);
    setApplied({ startDate: s, endDate: e, method, fxSplit });
  };
  // DateField 수동 편집 시 preset=직접 지정 으로 전환(칩 하이라이트 일관)
  const onStartEdit = (v: string) => { setStartDate(v); setPreset("custom"); };
  const onEndEdit = (v: string) => { setEndDate(v); setPreset("custom"); };

  const { data, isLoading, error, isFetching } = useBrinson({
    code: fundCode,
    startDate: applied.startDate,
    endDate: applied.endDate,
    mappingMethod: applied.method,
    paMethod: "8", // 8분류 고정 (사용자 요구사항 1)
    fxSplit: applied.fxSplit,
    saaMode,
  });

  // 기간별(1M/3M/6M/1Y/YTD/SI) Brinson 효과 — 하단 요인효과 토글 시에만 조회(콜드 6× 비용).
  const needPeriods = trendMode !== "all" || factorToggle;
  const periodsQ = useBrinsonPeriods({
    code: fundCode,
    endDate: applied.endDate,
    mappingMethod: applied.method,
    paMethod: "8",
    fxSplit: applied.fxSplit,
    saaMode,
    enabled: needPeriods,
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

  // 수익률 분석 모드/선택 자산군 (controlled). 기간 효과표가 같은 효과/자산군을 따른다.
  const trendClasses = enrichedRows.map((r) => r.asset_class); // ROW_ORDER 정렬됨
  const effSel = trendMode === "all"
    ? ""
    : (trendSel && trendClasses.includes(trendSel) ? trendSel : (trendClasses[0] ?? ""));
  // 기간별 효과 조회 결과 (period → DTO). 선택 자산군 행 추출용.
  const periodByKey = new Map((periodsQ.data?.periods ?? []).map((p) => [p.period, p]));
  const periodLoading = needPeriods && periodsQ.isLoading;
  // 기간별 효과표 계산중 플래시 — 최초(isLoading)뿐 아니라 조건 변경 refetch(isFetching)도 표시.
  // (백엔드가 6개 기간을 순차 full compute 하므로 콜드 시 수 분 걸릴 수 있음)
  const periodFetching = needPeriods && periodsQ.isFetching;
  const BM_LBL = data.bm_source === "SAA" ? "SAA" : "BM";

  // 기간별 효과표 행 정의 (Allocation/Selection = 선택 자산군 분해, factor = 포트 합계).
  type CRow = { label: string; get: (r: BrinsonPeriodRowDTO) => string; cls?: (r: BrinsonPeriodRowDTO) => string; bold?: boolean };
  // 자산배분효과 ≈ (a) AP−BM 비중차 × (b) BM 자산군수익률  (비중=기간평균, 경로적분이라 근사)
  const allocRows: CRow[] = [
    { label: `(a) AP−${BM_LBL} 비중차`, get: (r) => fmtPct(r.ap_weight - r.bm_weight), cls: (r) => rc(r.ap_weight - r.bm_weight) },
    { label: `(b) 자산군수익률(${BM_LBL})`, get: (r) => fmtPct(r.bm_return), cls: (r) => rc(r.bm_return) },
    { label: "(c) 자산배분효과 (a×b)", get: (r) => fmtPct(r.alloc_effect, 3), cls: (r) => ec(r.alloc_effect), bold: true },
  ];
  // 종목선택효과 ≈ (a) BM비중 × (b) AP−BM 수익률차
  const selectRows: CRow[] = [
    { label: `(a) ${BM_LBL}비중`, get: (r) => fmtWeight(r.bm_weight) },
    { label: `(b) AP−${BM_LBL} 수익률차`, get: (r) => fmtPct(r.ap_return - r.bm_return), cls: (r) => rc(r.ap_return - r.bm_return) },
    { label: "(c) 종목선택효과 (a×b)", get: (r) => fmtPct(r.select_effect, 3), cls: (r) => ec(r.select_effect), bold: true },
  ];
  type FRow = { label: string; get: (p: BrinsonPeriodDTO) => number; bold?: boolean };
  const factorRows: FRow[] = [
    { label: "자산배분효과", get: (p) => p.total_alloc },
    { label: "종목선택효과", get: (p) => p.total_select },
    { label: "교차효과", get: (p) => p.total_cross },
    { label: "초과수익", get: (p) => p.total_excess, bold: true },
  ];

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
  // 유동성및기타 collapse — 편입종목 탭 collapseLiquidity 와 동일 규칙(2026-06 합의):
  // 예금·USD Deposit·현금/미수금·환매미지급금만 개별 노출, 나머지(콜론·MMF 등)는 "기타" 합산.
  // 기여=합산, Normalized 수익률=비중가중평균.
  const liq1 = apSecByClass1.get("유동성및기타");
  if (liq1) {
    const keep: typeof liq1 = [];
    let etcW = 0, etcC = 0, etcRW = 0, hasEtc = false;
    for (const x of liq1) {
      if (isLiqKeep(x.item_nm)) keep.push(x);
      else { etcW += x.weight; etcC += x.contrib; etcRW += x.ret * x.weight; hasEtc = true; }
    }
    if (hasEtc) keep.push({ item_nm: "기타", weight: etcW, contrib: etcC, ret: etcW !== 0 ? etcRW / etcW : 0 });
    apSecByClass1.set("유동성및기타", keep);
  }
  // 자산군별 BM 지수 배열(기여/수익률 포함) — name===자산군명(MP 목표비중뿐)은 제외, FX 제외.
  // 펼침 시 지수당 개별 상세 행(자산군 컬럼 하위 들여쓰기 + 지수별 기여/수익률)으로 표기.
  type BmCompX = { name: string; contrib?: number | null; ret?: number | null };
  const bmNamesByClass1 = new Map<string, BmCompX[]>();
  for (const c of data.bm_components) {
    if (c.asset_class === "FX") continue;
    if (!c.name || c.name === c.asset_class) continue;
    const g = normCls1(c.asset_class);
    const arr = bmNamesByClass1.get(g) ?? [];
    const cx = c as unknown as BmCompX; // openapi 재생성 전 임시 확장 (contrib/ret 신규 필드)
    arr.push({ name: c.name, contrib: cx.contrib ?? null, ret: cx.ret ?? null });
    bmNamesByClass1.set(g, arr);
  }
  // ── 표0(BM/SAA 구성) 데이터 준비 — 컴포넌트 레벨로 호이스팅해 표1과 상세 행수 공유 ──
  const isBM0 = data.bm_source === "BM";
  const saaByClass0 = new Map<string, { label: string; weight: number }[]>();
  for (const c of data.bm_components) {
    if (c.asset_class === "FX") continue;
    const g = normCls1(c.asset_class);
    const arr = saaByClass0.get(g) ?? [];
    // BM=지수명. SAA=등록/proxy 인덱스명(name). MP 목표비중 SAA는 name===자산군명이라 "—".
    const idxName = c.name && c.name !== c.asset_class ? c.name : "—";
    arr.push({ label: idxName, weight: c.weight });
    saaByClass0.set(g, arr);
  }
  // 자산군별 AP — 기말 보유 스냅샷(ap_composition, 현금·미수금 포함) 우선, 없으면 period sec_contrib.
  const apComp0 = data.ap_composition ?? [];
  const useSnapshot0 = apComp0.length > 0;
  const apByClass0 = new Map<string, { label: string; weight: number }[]>();
  const apSnapSub0 = new Map<string, number>();
  if (useSnapshot0) {
    for (const c of apComp0) {
      const g = normCls1(c.asset_class);
      apByClass0.set(g, c.items.map((it) => ({ label: it.item_nm, weight: it.weight_pct })));
      apSnapSub0.set(g, (apSnapSub0.get(g) ?? 0) + c.weight_pct);
    }
  } else {
    for (const s of data.sec_contrib) {
      if (s.asset_class === "FX") continue;
      const g = normCls1(s.asset_class);
      const arr = apByClass0.get(g) ?? [];
      arr.push({ label: s.item_nm, weight: s.weight_pct });
      apByClass0.set(g, arr);
    }
    for (const arr of apByClass0.values()) arr.sort((a, b) => b.weight - a.weight);
  }
  // 기간 중 보유이력이 있으나 기말 미보유인 종목(예: 08K88 ACE 200TR)도 AP에 포함, 비중 0% 표기
  // — 표1(기간 기여수익률)과 종목 구성 일치 (사용자 지정 2026-07-03, 의도=패널 좌우 밸런스).
  if (useSnapshot0) {
    for (const s of data.sec_contrib) {
      if (s.asset_class === "FX") continue;
      if (s.item_nm === s.asset_class) continue; // 잔차/집계 행 제외
      const g = normCls1(s.asset_class);
      const arr = apByClass0.get(g) ?? [];
      if (!arr.some((x) => x.label === s.item_nm)) arr.push({ label: s.item_nm, weight: 0 });
      apByClass0.set(g, arr);
    }
  }
  // 유동성및기타 collapse — 편입종목 탭 collapseLiquidity 와 동일 규칙(2026-06 합의)
  const liq0 = apByClass0.get("유동성및기타");
  if (liq0) {
    const keep: { label: string; weight: number }[] = [];
    let etcW0 = 0, hasEtc0 = false;
    for (const x of liq0) {
      if (isLiqKeep(x.label)) keep.push(x);
      else { etcW0 += x.weight; hasEtc0 = true; }
    }
    if (hasEtc0) keep.push({ label: "기타", weight: etcW0 });
    apByClass0.set("유동성및기타", keep);
  }
  // 소계: 스냅샷이면 ap_composition, 아니면 asset_rows(period). BM 소계는 항상 asset_rows.
  const subByClass0 = new Map(enrichedRows.map((r) => [r.asset_class, r]));
  // 자산군 합집합(FX 제외) → ROW_ORDER 순
  const classes0 = [...new Set([...saaByClass0.keys(), ...apByClass0.keys()])]
    .filter((g) => g !== "FX")
    .sort((a, b) => (ROW_ORDER_MAP.get(a) ?? 99) - (ROW_ORDER_MAP.get(b) ?? 99));
  const bmComps0 = new Map(classes0.map((g) => [g,
    (saaByClass0.get(g) ?? [])
      .filter((s) => s.label && s.label !== "—")
      .sort((a, b) => b.weight - a.weight)]));

  // ── 상세 행수 공유(패널 간 표0↔표1 + 패널 내 좌↔우 라인 정렬) ──
  // 펼침 시 자산군별 행수 = max(표0 BM 지수, 표0 AP 종목, 표1 AP 종목+잔차, 표1 BM 지수) —
  // 네 테이블 전부 이 수만큼 채워(빈 행 패딩) 자산군 라인이 화면 전체에서 일치.
  const detailShared = new Map<string, number>();
  if (tbl0Expanded) {
    const allCls = new Set<string>([...classes0, ...enrichedRows.map((r) => r.asset_class)]);
    for (const g of allCls) {
      const n0 = Math.max((bmComps0.get(g) ?? []).length, (apByClass0.get(g) ?? []).length);
      const secs = apSecByClass1.get(g) ?? [];
      let n1 = secs.length;
      const r = enrichedRows.find((x) => x.asset_class === g);
      if (tbl1Metric !== "norm" && r) {
        const secSum = secs.reduce((s, x) => s + x.contrib, 0);
        if (Math.abs(r.contrib_return - secSum) >= 0.005) n1 += 1; // 기타(잔차) 행
      }
      n1 = Math.max(n1, (bmNamesByClass1.get(g) ?? []).length);
      detailShared.set(g, Math.max(n0, n1));
    }
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

  // 기간별 수익률 표 데이터 — 조회 종료일 앵커(/period-returns). 값은 분수 → *100.
  const pr = prq.data?.period_returns ?? {};
  const bmpr = prq.data?.bm_period_returns ?? {};

  // 위험조정 지표(연환산·샤프 등) — KPI 연환산 인라인과 위험지표 스트립이 동일 소스 사용.
  const hasBm = data.bm_source !== "none";
  const metrics = computeBrinsonMetrics(data.daily_brinson, data.rf_period);

  return (
    <section className="bn-root">
      {/* 펀드 변경 시 기간 보정 안내 팝업 (8초 자동 소멸) */}
      {adjustNote && (
        <div className="bn-adjust-pop" role="status">
          <span>ⓘ {adjustNote}</span>
          <button type="button" onClick={() => setAdjustNote(null)} aria-label="닫기">×</button>
        </div>
      )}
      {/* 헤더 */}
      <div className="bn-head">
        <h2 className="fund-title">
          {data.fund_name} <span className="code">{data.fund_code}</span>
        </h2>
        {isFetching && <span className="bn-tag recalc">● 재계산 중…</span>}
      </div>
      {isFetching && (
        <div style={{ marginTop: -8 }}>
          <BrinsonProgressBar label="재계산 중 (조건 변경)" height={4} />
        </div>
      )}

      {/* 기간 preset 칩 (거래내역 탭 동일). 클릭 시 즉시 조회. */}
      <div className="bn-card bn-presets">
        {BN_PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            className={`bn-chip ${preset === p.key ? "on" : ""}`}
            onClick={() => applyPreset(p.key)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* 컨트롤 카드 */}
      <div className="bn-card bn-ctrl">
        <label className="bn-field">
          시작
          <DateField value={startDate} onChange={onStartEdit} />
        </label>
        <label className="bn-field">
          종료
          <DateField value={endDate} onChange={onEndEdit} />
        </label>
        <label className="bn-field">
          분류
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value as BrinsonMappingMethod)}
            title={"자산군 분류 기준 (FX·유동성은 모든 방식 공통)"}
          >
            {MAPPING_METHODS.map((m) => (
              <option key={m} value={m}>
                {METHOD_LABEL[m]}
              </option>
            ))}
          </select>
        </label>
        <label className="bn-field">
          FX
          <select
            value={fxSplit ? "split" : "incl"}
            onChange={(e) => setFxSplit(e.target.value === "split")}
            title={
              "FX 포함: 환효과를 해외주식/해외채권 수익률에 접어넣음 (별도 FX 자산군 없음)\nFX 분리: 환효과를 별도 FX 자산군으로 분리"
            }
          >
            <option value="incl">FX 포함</option>
            <option value="split">FX 분리</option>
          </select>
        </label>
        {/* 소스: 등록 SAA ↔ proxy (SAA 펀드만). 비중: 고정(constant-mix) ↔ drift(buy-and-hold, 전체) */}
        {data.bm_source !== "BM" && (
          <label className="bn-field">
            소스
            <select
              value={saaSource}
              onChange={(e) => setSaaSource(e.target.value as "auto" | "proxy")}
              disabled={isFetching}
              title={
                "등록 SAA: 등록된 SAA 인덱스\nproxy: 안전자산(채권 ex-HY)→KIS 종합채권 / 나머지→MSCI ACWI"
              }
            >
              <option value="auto">등록 SAA</option>
              <option value="proxy">proxy (MSCI ACWI · KIS 종합채권)</option>
            </select>
          </label>
        )}
        <label className="bn-field">
          비중
          <select
            value={weightMode}
            onChange={(e) => setWeightMode(e.target.value as "fixed" | "drift")}
            disabled={isFetching}
            title={
              "고정(constant-mix): 매일 목표비중 리밸런싱\ndrift(buy-and-hold): 리밸 target에서 인덱스 수익률대로 비중 표류"
            }
          >
            <option value="fixed">고정</option>
            <option value="drift">drift</option>
          </select>
        </label>
        <button type="button" className="bn-apply" onClick={onApply} disabled={!isDirty || isFetching}>
          {isFetching ? "조회 중…" : "조회"}
        </button>
        <button
          type="button"
          className="bn-apply"
          onClick={onExport}
          disabled={exporting || isFetching || isDirty}
          title={isDirty ? "변경된 조건을 먼저 조회한 뒤 내려받을 수 있습니다" : "현재 조회조건 스냅샷을 엑셀로 내려받기 (최초 생성은 수십 초 소요)"}
        >
          {exporting ? "엑셀 생성 중…" : "내려받기"}
        </button>
        {isDirty && !isFetching && (
          <span className="bn-dirty">변경됨 — 조회를 눌러 갱신</span>
        )}
      </div>

      {/* KPI 6카드 — Overview 지표카드 서식: 상단 라벨(좌)+값(우) / 하단 보조행 (2026-07-08) */}
      <div className="bn-kpis">
        <div className="bn-kpi">
          <div className="bn-kpi-top">
            <span className="k">AP 수익률</span>
            <span className={`v num ${rc(data.period_ap_return)}`}>{fmtPct(data.period_ap_return)}</span>
          </div>
          <div className="cmp">
            {metrics.valid ? <>연환산 <span className="num">{fmtPct(metrics.apAnnRet)}</span></> : <span className="num">{" "}</span>}
          </div>
        </div>
        {/* 벤치마크 없는 펀드(2JM23)는 BM·초과 카드를 띄우지 않는다 — BM=0 이라
            초과가 AP 전액으로 표시돼 오해를 준다 (2026-07-29) */}
        {hasBm && (
          <div className="bn-kpi">
            <div className="bn-kpi-top">
              <span className="k">BM 수익률</span>
              <span className={`v num ${rc(data.period_bm_return)}`}>{fmtPct(data.period_bm_return)}</span>
            </div>
            <div className="cmp">
              {metrics.valid ? <>연환산 <span className="num">{fmtPct(metrics.bmAnnRet)}</span></> : <span className="num">{" "}</span>}
            </div>
          </div>
        )}
        {hasBm && (
          <div className="bn-kpi">
            <div className="bn-kpi-top">
              <span className="k">초과수익률</span>
              <span className={`v num ${ec(data.total_excess)}`}>{fmtPct(data.total_excess)}</span>
            </div>
            <div className="cmp">
              {metrics.valid ? <>연환산 <span className="num">{fmtPct(metrics.annExcess)}</span></> : <span className="num">{" "}</span>}
            </div>
          </div>
        )}
        {/* 스냅샷 3카드 — 종료일 기준값 + 시작일 대비 변동 (2026-07-07 사용자 지정) */}
        <div className="bn-kpi">
          <div className="bn-kpi-top">
            <span className="k">설정액</span>
            <span className="v num">{kpiSnap.setupEnd != null ? `${(kpiSnap.setupEnd / 1e8).toFixed(1)}억` : "—"}</span>
          </div>
          <div className="cmp">
            기간변동{" "}
            <span className={`delta ${kpiSnap.setupNetEok >= 0 ? "up" : "dn"} num`}>
              {kpiSnap.setupNetEok >= 0 ? "+" : "−"}{Math.abs(kpiSnap.setupNetEok).toFixed(1)}억
              {kpiSnap.setupPct != null ? ` (${kpiSnap.setupPct >= 0 ? "+" : ""}${(kpiSnap.setupPct * 100).toFixed(1)}%)` : ""}
            </span>
          </div>
        </div>
        <div className="bn-kpi">
          <div className="bn-kpi-top">
            <span className="k">순자산 (NAV)</span>
            <span className="v num">{kpiSnap.nast1 != null ? `${(kpiSnap.nast1 / 1e8).toFixed(1)}억` : "—"}</span>
          </div>
          <div className="cmp">
            {kpiSnap.nastD != null ? (
              <>
                기간변동{" "}
                <span className={`delta ${kpiSnap.nastD >= 0 ? "up" : "dn"} num`}>
                  {kpiSnap.nastD >= 0 ? "+" : "−"}{Math.abs(kpiSnap.nastD / 1e8).toFixed(1)}억
                  {kpiSnap.nastPct != null ? ` (${kpiSnap.nastPct >= 0 ? "+" : ""}${(kpiSnap.nastPct * 100).toFixed(1)}%)` : ""}
                </span>
              </>
            ) : <span className="num">{" "}</span>}
          </div>
        </div>
        <div className="bn-kpi">
          <div className="bn-kpi-top">
            <span className="k">기준가</span>
            <span className="v num">{kpiSnap.price1 != null ? kpiSnap.price1.toFixed(2) : "—"}</span>
          </div>
          <div className="cmp">
            {kpiSnap.priceD != null ? (
              <>
                기간변동{" "}
                <span className={`delta ${kpiSnap.priceD >= 0 ? "up" : "dn"} num`}>
                  {kpiSnap.priceD >= 0 ? "+" : "−"}{Math.abs(kpiSnap.priceD).toFixed(2)}
                  {kpiSnap.pricePct != null ? ` (${kpiSnap.pricePct >= 0 ? "+" : ""}${(kpiSnap.pricePct * 100).toFixed(2)}%)` : ""}
                </span>
              </>
            ) : <span className="num">{" "}</span>}
          </div>
        </div>
      </div>

      {/* 위험지표 (전폭 카드) */}
      {metrics.valid && (
        <div className="bn-card">
          <BrinsonMetricsPanel daily={data.daily_brinson} hasBm={hasBm} rfPeriod={data.rf_period} />
        </div>
      )}

      {isFallback && (
        <div className="bn-warn">
          ⚠️ Brinson 계산 실패 — fallback. {data.meta.warnings.join(" / ")}
        </div>
      )}

      {/* BM 구성지수 소스 신선도 (Bloomberg 피드 정지 대응) — 계산은 정상이므로 fallback 과 별도 */}
      {!isFallback && data.meta.warnings.length > 0 && (
        <div className="bn-warn" style={{ background: "#fffbeb", color: "#92400e" }}>
          <div style={{ fontWeight: 700, marginBottom: 4 }}>BM 데이터 소스 안내</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {data.meta.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 벤치마크(BM)구성 | 자산군별 기여수익률 — side-by-side (전폭) */}
      <div className="bn-cols">
          {/* 표 0: BM/SAA 구성 vs AP 실제 */}
          {data.bm_source !== "none" && (() => {
            // 데이터 준비는 컴포넌트 레벨(saaByClass0 등)로 호이스팅 — 표1과 상세 행수(detailShared) 공유
            const isBM = isBM0;
            const saaByClass = saaByClass0;
            const apByClass = apByClass0;
            const apSnapSub = apSnapSub0;
            const useSnapshot = useSnapshot0;
            const subByClass = subByClass0;
            const classes = classes0;
            const detail0 = detailShared;

            return (
              <div className="bn-card bn-sec">
                <div className="bn-head2">
                  <h3>{isBM ? "벤치마크(BM) 구성" : "전략적 자산배분(SAA) 구성"}</h3>
                  <span className="sub">목표 셋팅 vs AP 기말 보유 (현금 포함·FX 제외)</span>
                  <div className="right">
                    <button type="button" className="bn-tgl" onClick={() => setTbl0Expanded((v) => !v)}>
                      {tbl0Expanded ? "▲ 접기" : "▼ 종목 펼치기"}
                    </button>
                  </div>
                </div>
                {/* 좌=BM / 우=AP 분리 테이블 (사용자 지정 2026-07-02) */}
                <div className="bn-split">
                  <table className="bn-tbl">
                    <colgroup>
                      <col />
                      <col style={{ width: 96 }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>자산군</th>
                        <th className="r">{isBM ? "BM비중" : "SAA비중"}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {classes.flatMap((g) => {
                        const saa = saaByClass.get(g) ?? [];
                        const sub = subByClass.get(g);
                        const bmSub = sub?.bm_weight ?? saa.reduce((s, x) => s + x.weight, 0);
                        // 접힘: 자산군 소계만. 펼침: 지수(티커)별 개별 행 + 각 비중 (AP 측과 동일 패턴)
                        const rows: ReactNode[] = [
                          <tr key={`${g}-bm`} className="clsrow">
                            <td>{g}</td>
                            <td className="r">{fmtWeight(bmSub, 1)}</td>
                          </tr>,
                        ];
                        if (tbl0Expanded) {
                          const comps = bmComps0.get(g) ?? [];
                          for (let i = 0; i < comps.length; i++) {
                            rows.push(
                              <tr key={`${g}-bmi-${i}`}>
                                <td className="ind">{comps[i].label}</td>
                                <td className="r">{fmtWeight(comps[i].weight, 1)}</td>
                              </tr>,
                            );
                          }
                          rows.push(...padRows(`${g}-bml`, (detail0.get(g) ?? 0) - comps.length, 2));
                        }
                        return rows;
                      })}
                    </tbody>
                  </table>
                  <table className="bn-tbl">
                    <colgroup>
                      <col />
                      {/* AP비중 112 / 차이 102 — 자산군별 기여 표(112/84)와 시각적 갭 일치.
                          차이 값(+63.6%p)이 초과기여(+1.10%)보다 넓어 컬럼폭을 더 줌 (2026-07-10) */}
                      <col style={{ width: 112 }} />
                      <col style={{ width: 102 }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>AP</th>
                        <th className="r">AP비중</th>
                        <th className="r" title="AP비중 − BM비중 (%p)">차이</th>
                      </tr>
                    </thead>
                    <tbody>
                      {classes.flatMap((g) => {
                        const saa = saaByClass.get(g) ?? [];
                        const ap = apByClass.get(g) ?? [];
                        const sub = subByClass.get(g);
                        const apSub = useSnapshot ? (apSnapSub.get(g) ?? 0) : (sub?.ap_weight ?? ap.reduce((s, x) => s + x.weight, 0));
                        const bmSub = sub?.bm_weight ?? saa.reduce((s, x) => s + x.weight, 0);
                        const diff = apSub - bmSub;
                        const rows: ReactNode[] = [
                          <tr key={`${g}-cls`} className="clsrow">
                            <td>{g}</td>
                            <td className="r">{fmtWeight(apSub, 1)}</td>
                            <td className={`r b ${diff >= 0 ? "ok" : "brw"}`}>
                              {diff >= 0 ? "+" : ""}{diff.toFixed(1)}%p
                            </td>
                          </tr>,
                        ];
                        // 펼침 시 AP 종목 행 + 좌측(BM)과 행수 맞춤 패딩
                        if (tbl0Expanded) {
                          for (let i = 0; i < ap.length; i++) {
                            rows.push(
                              <tr key={`${g}-ap-${i}`}>
                                <td className="ind" title={ap[i].label}>{ap[i].label}</td>
                                <td className="r">{fmtWeight(ap[i].weight, 1)}</td>
                                <td className="r" />
                              </tr>,
                            );
                          }
                          rows.push(...padRows(`${g}-apl`, (detail0.get(g) ?? 0) - ap.length, 3));
                        }
                        return rows;
                      })}
                    </tbody>
                  </table>
                </div>
                {!isBM && (
                  data.bm_components.some((c) => c.name && c.name !== c.asset_class) ? (
                    <div className="bn-note">※ SAA 벤치마크(등록 인덱스) 기준 — 수익률·기여 분해 제공.</div>
                  ) : (
                    <div className="bn-note">
                      ※ BM 미설정 펀드 — SAA(MP) 목표비중으로 비중만 비교 (수익률/기여 분해는 미제공).
                    </div>
                  )
                )}
              </div>
            );
          })()}

          {/* 표 1: 자산군별 기여수익률 (BM기여 + 초과기여) */}
          <div className="bn-card bn-sec">
            <div className="bn-head2">
              <h3>자산군별 {tbl1Metric === "norm" ? "수익률(Normalized)" : "기여수익률"}</h3>
              <div className="right">
                <button type="button" className="bn-tgl" onClick={() => setTbl0Expanded((v) => !v)}>
                  {tbl0Expanded ? "▲ 접기" : "▼ 종목 펼치기"}
                </button>
                <span className="bn-seg">
                  {(
                    [
                      ["contrib", "기여"],
                      ["norm", "Normalized"],
                    ] as const
                  ).map(([m, label]) => (
                    <button
                      key={m}
                      type="button"
                      className={tbl1Metric === m ? "on" : ""}
                      onClick={() => setTbl1Metric(m)}
                      title={
                        m === "contrib"
                          ? "기여수익률 = 배분비중 × 자산군수익률 (합 = 포트 수익률)"
                          : "순수 수익률 (편입비중 반영X)"
                      }
                    >
                      {label}
                    </button>
                  ))}
                </span>
              </div>
            </div>
            {/* 좌=BM / 우=AP 분리 테이블 (사용자 지정 2026-07-02) */}
            <div className="bn-split">
              {hasBm && (
              <table className="bn-tbl">
                <colgroup>
                  <col />
                  <col style={{ width: tbl1Metric === "norm" ? 134 : 96 }} />
                </colgroup>
                <thead>
                  <tr>
                    <th>자산군</th>
                    <th className="r">{tbl1Metric === "norm" ? `${BM_LBL}수익률(Norm.)` : `${BM_LBL}수익률`}</th>
                  </tr>
                </thead>
                <tbody>
                  {enrichedRows.flatMap((r) => {
                    const names = bmNamesByClass1.get(r.asset_class) ?? [];
                    const bmVal = tbl1Metric === "norm" ? r.bm_return : r.bm_contrib;
                    // 지수 컬럼 없음 — 펼침 시 지수를 자산군 컬럼 하위(들여쓰기) 행으로 표기 (사용자 지정 2026-07-03)
                    const rows: ReactNode[] = [
                      <tr key={r.asset_class} className="clsrow">
                        <td>{r.asset_class}</td>
                        <td className={`r ${rc(bmVal)}`}>{fmtPct(bmVal)}</td>
                      </tr>,
                    ];
                    if (tbl0Expanded) {
                      for (let i = 0; i < names.length; i++) {
                        const cv = tbl1Metric === "norm" ? names[i].ret : names[i].contrib;
                        rows.push(
                          <tr key={`${r.asset_class}-bmn-${i}`}>
                            <td className="muted ind" title={names[i].name}>{names[i].name}</td>
                            <td className={`r ${cv != null ? rc(cv) : ""}`}>{cv != null ? fmtPct(cv) : ""}</td>
                          </tr>,
                        );
                      }
                      rows.push(...padRows(`${r.asset_class}-bm1`,
                        (detailShared.get(r.asset_class) ?? 0) - names.length, 2));
                    }
                    return rows;
                  })}
                  {tbl1Metric !== "norm" && (
                    <tr className="tot">
                      <td>합계</td>
                      <td className={`r ${rc(sumBmContrib)}`}>{fmtPct(sumBmContrib)}</td>
                    </tr>
                  )}
                </tbody>
              </table>
              )}
              <table className="bn-tbl">
                <colgroup>
                  <col />
                  <col style={{ width: tbl1Metric === "norm" ? 134 : 112 }} />
                  {hasBm && tbl1Metric !== "norm" && <col style={{ width: 84 }} />}
                </colgroup>
                <thead>
                  <tr>
                    <th>AP</th>
                    <th
                      className="r"
                      title="금액가중(money-weighted) 수익률로, 기간 중 매매·포지션 사이징이 반영됩니다."
                    >
                      {tbl1Metric === "norm" ? "AP수익률(Norm.)" : "AP수익률"}
                      <span className="muted" style={{ fontWeight: 400, marginLeft: 3 }}>ⓘ</span>
                    </th>
                    {hasBm && tbl1Metric !== "norm" && <th className="r">초과기여</th>}
                  </tr>
                </thead>
                <tbody>
                  {enrichedRows.flatMap((r) => {
                    const isNorm = tbl1Metric === "norm";
                    const showExcess = hasBm && !isNorm;   // BM 없으면 초과 개념 없음
                    const apVal = isNorm ? r.ap_return : r.contrib_return;
                    const rows: ReactNode[] = [
                      <tr key={r.asset_class} className="clsrow">
                        <td>{r.asset_class}</td>
                        <td className={`r b ${rc(apVal)}`}>{fmtPct(apVal)}</td>
                        {showExcess && (
                          <td className={`r b ${xc(r.excess_contrib)}`}>{fmtPct(r.excess_contrib)}</td>
                        )}
                      </tr>,
                    ];
                    // 펼침 시 AP 종목 행 — 표0 과 동일 행수, 표0 토글과 연동
                    if (tbl0Expanded) {
                      const secs = apSecByClass1.get(r.asset_class) ?? [];
                      for (let i = 0; i < secs.length; i++) {
                        const secVal = isNorm ? secs[i].ret : secs[i].contrib;
                        rows.push(
                          <tr key={`${r.asset_class}-sec-${i}`}>
                            <td className="ind" title={secs[i].item_nm}>{secs[i].item_nm}</td>
                            <td className={`r ${rc(secVal)}`}>{fmtPct(secVal)}</td>
                            {showExcess && <td className="r" />}
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
                              <td className="resid">기타(잔차)</td>
                              <td className={`r ${rc(resid)}`}>{fmtPct(resid)}</td>
                              {showExcess && <td className="r" />}
                            </tr>,
                          );
                        }
                      }
                      // 좌측(BM 지수 행)이 더 많으면 빈 행 패딩 → 자산군 라인 좌우 일치
                      rows.push(...padRows(`${r.asset_class}-ap1`,
                        (detailShared.get(r.asset_class) ?? 0) - (rows.length - 1), showExcess ? 3 : 2));
                    }
                    return rows;
                  })}
                  {tbl1Metric !== "norm" && (
                    <tr className="tot">
                      <td>합계</td>
                      <td className={`r ${rc(sumApContrib)}`}>{fmtPct(sumApContrib)}</td>
                      {hasBm && (
                        <td className={`r ${xc(sumExcessContrib)}`}>{fmtPct(sumExcessContrib)}</td>
                      )}
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
      </div>

      {/* 본문 2×2 그리드: [좌상 분석표+워터폴 | 우상 수익률분석] / [좌하 요인추이 | 우하 종목표] */}
      <div className="bn-grid">
        {/* ── 좌상: Brinson 분석표 + 워터폴 ──
            벤치마크 없는 펀드(2JM23)는 Alloc/Select/Cross·초과 분해가 정의되지 않는다
            (BM비중 0 → 전액 Cross). AP 기여만 남기고 통째로 감춘다 (2026-07-29) */}
        {hasBm && (
        <div className="bn-stack">
          {/* Brinson 분석 (자산군별 Alloc/Select/Cross) */}
          <div className="bn-card bn-sec">
            <div className="bn-head2">
              <h3>Brinson 분석 (자산배분효과 / 종목선택효과 / 교차효과)</h3>
            </div>
            <table className="bn-tbl">
              <thead>
                <tr>
                  <th>자산군</th>
                  <th className="r">자산배분효과</th>
                  <th className="r">종목선택효과</th>
                  <th className="r">교차효과</th>
                  <th className="r">자산군 별</th>
                </tr>
              </thead>
              <tbody>
                {enrichedRows.map((r) => {
                  const rowSum = r.alloc_effect + r.select_effect + r.cross_effect;
                  return (
                    <tr key={r.asset_class}>
                      <td>{r.asset_class}</td>
                      <td className={`r ${rc(r.alloc_effect)}`}>{fmtPct(r.alloc_effect, 3)}</td>
                      <td className={`r ${rc(r.select_effect)}`}>{fmtPct(r.select_effect, 3)}</td>
                      <td className={`r ${rc(r.cross_effect)}`}>{fmtPct(r.cross_effect, 3)}</td>
                      <td className={`r b ${rc(rowSum)}`}>{fmtPct(rowSum, 3)}</td>
                    </tr>
                  );
                })}
                <tr className="tot">
                  <td>요인 합계</td>
                  <td className={`r ${rc(data.total_alloc)}`}>{fmtPct(data.total_alloc, 3)}</td>
                  <td className={`r ${rc(data.total_select)}`}>{fmtPct(data.total_select, 3)}</td>
                  <td className={`r ${rc(data.total_cross)}`}>{fmtPct(data.total_cross, 3)}</td>
                  <td className={`r ${rc(data.total_excess)}`}>{fmtPct(data.total_excess)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 초과성과 요인분해 워터폴 (height 키워 우상 수익률분석과 바닥선 근사) */}
          <div className="bn-card bn-sec">
            <div className="bn-head2">
              <h3>초과성과 요인분해</h3>
            </div>
            <BrinsonWaterfall
              alloc={data.total_alloc}
              select={data.total_select}
              cross={data.total_cross}
              excess={data.total_excess}
              height={420}
            />
          </div>
        </div>
        )}

        {/* ── 우상: 수익률 분석 + 기간별 수익률 표 ── */}
          <div className="bn-card bn-sec">
            <BrinsonTrendPanel
              daily={data.daily_brinson}
              dailyClass={data.daily_class ?? []}
              bmSource={data.bm_source}
              bmComponents={data.bm_components ?? []}
              height={460}
              mode={trendMode}
              onMode={setTrendMode}
              sel={trendSel}
              onSel={setTrendSel}
            />
            <div className="bn-ptbl">
              {trendMode === "all" ? (
                <>
                  <div className="t" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span>
                      {factorToggle ? "기간별 요인효과" : "기간별 수익률"}
                      <span style={{ fontWeight: 400, color: "#9ca3af", marginLeft: 6 }}>(기준 {applied.endDate})</span>
                    </span>
                    {factorToggle && periodFetching && (
                      <span className="bn-tag recalc">● 기간별 효과 계산 중… (기간 6개 순차 계산, 최초 수 분 소요)</span>
                    )}
                    {!factorToggle && prq.isFetching && (
                      <span className="bn-tag recalc">● 계산 중…</span>
                    )}
                    {hasBm && (
                    <span style={{ marginLeft: "auto", display: "inline-flex", border: "1px solid #d1d5db", borderRadius: 4, overflow: "hidden" }}>
                      {([["수익률", false], ["요인효과", true]] as const).map(([lbl, on]) => (
                        <button key={lbl} onClick={() => setFactorToggle(on)}
                          style={{ fontSize: 11, padding: "3px 10px", border: "none", cursor: "pointer",
                            background: factorToggle === on ? "#2563eb" : "#fff", color: factorToggle === on ? "#fff" : "#374151" }}>
                          {lbl}
                        </button>
                      ))}
                    </span>
                    )}
                  </div>
                  {!factorToggle || !hasBm ? (
                    <table className="bn-tbl">
                      <thead>
                        <tr><th>구분</th>{PERIOD_COLS.map(([k, label]) => <th key={k} className="r">{label}</th>)}</tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>AP 수익률</td>
                          {PERIOD_COLS.map(([k]) => { const v = pr[k]; return <td key={k} className={`r ${v != null ? rc(v) : ""}`}>{v != null ? fmtPct(v * 100) : (prq.isFetching ? "…" : "—")}</td>; })}
                        </tr>
                        {hasBm && (
                        <tr>
                          <td>{BM_LBL} 수익률</td>
                          {PERIOD_COLS.map(([k]) => { const v = bmpr[k]; return <td key={k} className={`r ${v != null ? rc(v) : ""}`}>{v != null ? fmtPct(v * 100) : (prq.isFetching ? "…" : "—")}</td>; })}
                        </tr>
                        )}
                        {hasBm && (
                        <tr>
                          <td>초과</td>
                          {PERIOD_COLS.map(([k]) => { const a = pr[k]; const b = bmpr[k]; const ex = a != null && b != null ? (a - b) * 100 : null; return <td key={k} className={`r b ${ex != null ? (ex < 0 ? "brw" : "ok") : ""}`}>{ex != null ? fmtPct(ex) : (prq.isFetching ? "…" : "—")}</td>; })}
                        </tr>
                        )}
                      </tbody>
                    </table>
                  ) : (
                    <table className="bn-tbl">
                      <thead>
                        <tr><th>요인</th>{PERIOD_COLS.map(([k, label]) => <th key={k} className="r">{label}</th>)}</tr>
                      </thead>
                      <tbody>
                        {factorRows.map((fr) => (
                          <tr key={fr.label}>
                            <td>{fr.label}</td>
                            {PERIOD_COLS.map(([k]) => {
                              const p = periodByKey.get(k);
                              const v = p ? fr.get(p) : null;
                              return <td key={k} className={`r ${fr.bold ? "b" : ""} ${v != null ? (fr.bold ? ec(v) : rc(v)) : ""}`}>{v != null ? fmtPct(v, 3) : (periodLoading ? "…" : "—")}</td>;
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              ) : (
                <>
                  <div className="t" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span>기간별 {trendMode === "alloc" ? "자산배분효과" : "종목선택효과"}{effSel ? ` — ${effSel}` : ""}</span>
                    {periodFetching && (
                      <span className="bn-tag recalc">● 계산 중… (기간 6개 순차 계산, 최초 수 분 소요)</span>
                    )}
                  </div>
                  <table className="bn-tbl">
                    <thead>
                      <tr><th>구분</th>{PERIOD_COLS.map(([k, label]) => <th key={k} className="r">{label}</th>)}</tr>
                    </thead>
                    <tbody>
                      {(trendMode === "alloc" ? allocRows : selectRows).map((cr) => (
                        <tr key={cr.label}>
                          <td>{cr.label}</td>
                          {PERIOD_COLS.map(([k]) => {
                            const row = periodByKey.get(k)?.rows.find((x) => x.asset_class === effSel);
                            return <td key={k} className={`r ${cr.bold ? "b" : ""} ${row && cr.cls ? cr.cls(row) : ""}`}>{row ? cr.get(row) : (periodLoading ? "…" : "—")}</td>;
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                    비중=기간 평균 · 효과(a×b)는 개념식 — 실제값은 일별 경로적분이라 (a)·(b) 곱과 다를 수 있음
                  </div>
                </>
              )}
            </div>
          </div>

        {/* ── 좌하: 요인별 초과수익 누적 추이 ── */}
        <div className="bn-stack">
          {hasBm && (
            <div className="bn-card bn-sec">
              <BrinsonFactorTrendChart daily={data.daily_brinson} />
            </div>
          )}
        </div>

        {/* ── 우하: 종목별 기여수익률 (전체 종목 + 비중 + 정렬) ── */}
          <div className="bn-card bn-sec">
            <div className="bn-head2">
              <h3>종목별 기여수익률</h3>
            </div>
            <table className="bn-tbl">
              <thead>
                <tr>
                  <th className="sort" onClick={() => onSecSort("asset_class")}>
                    자산군{sortGlyph("asset_class")}
                  </th>
                  <th className="sort" onClick={() => onSecSort("item_nm")}>
                    종목명{sortGlyph("item_nm")}
                  </th>
                  <th className="r sort" onClick={() => onSecSort("weight_pct")}>
                    비중{sortGlyph("weight_pct")}
                  </th>
                  <th className="r sort" onClick={() => onSecSort("return_pct")}>
                    수익률{sortGlyph("return_pct")}
                  </th>
                  <th className="r sort" onClick={() => onSecSort("contrib_pct")}>
                    기여수익률{sortGlyph("contrib_pct")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedSec.map((s, i) => (
                  <tr key={`${s.item_nm}-${i}`}>
                    <td>{s.asset_class}</td>
                    <td>{s.item_nm}</td>
                    <td className="r">{fmtWeight(s.weight_pct, 2)}</td>
                    <td className={`r ${rc(s.return_pct)}`}>{fmtPct(s.return_pct)}</td>
                    <td className={`r b ${rc(s.contrib_pct)}`}>{fmtPct(s.contrib_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
      </div>
    </section>
  );
}
