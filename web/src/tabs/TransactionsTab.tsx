import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  useFxPosition,
  useSecurities,
  useSecurityReturn,
  useTransactions,
  useWeightHistory,
  useAssetClassReturn,
} from "../hooks/useTransactions";
import { useFunds } from "../hooks/useFunds";
import WeightAreaChart from "../components/charts/WeightAreaChart";
import FxPositionChart from "../components/charts/FxPositionChart";
import FxHedgeGapChart from "../components/charts/FxHedgeGapChart";
import SecurityReturnChart from "../components/charts/SecurityReturnChart";
import type { WeightHistoryLevel } from "../api/endpoints";

interface Props {
  fundCode: string;
}

// 로컬 타임존 기준 YYYY-MM-DD (toISOString UTC 보정 회피)
function fmtLocal(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function monthsAgo(n: number): Date {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return d;
}
function startOfMonth(): Date {
  const d = new Date();
  return new Date(d.getFullYear(), d.getMonth(), 1);
}
function startOfYear(): Date {
  const d = new Date();
  return new Date(d.getFullYear(), 0, 1);
}

type TxnPreset = "MTD" | "1M" | "3M" | "6M" | "YTD" | "since" | "custom";

const TXN_PRESETS: { key: TxnPreset; label: string }[] = [
  { key: "MTD", label: "당월" },
  { key: "1M", label: "1개월" },
  { key: "3M", label: "3개월" },
  { key: "6M", label: "6개월" },
  { key: "YTD", label: "연초이후" },
  { key: "since", label: "설정후" },
  { key: "custom", label: "직접 지정" },
];

// 매수/매도/설정/해지/기타 → 손익 색 클래스 (ACE 토큰). 설정=유입(up), 해지=유출(dn)
const sideClass = (side: string) =>
  side.includes("매수") || side.includes("발행") || side.includes("설정")
    ? "up"
    : side.includes("매도") || side.includes("환매") || side.includes("해지")
      ? "dn"
      : "muted";

// 자산군 정렬 순서 (거래내역 asset_class 값 기준). 미정의는 뒤로(99).
const ASSET_ORDER: Record<string, number> = {
  국내주식: 0, 해외주식: 1, 국내채권: 2, 해외채권: 3,
  대체투자: 4, "금·대체": 4, FX: 5, 모펀드: 6, 유동성: 7,
};

export default function TransactionsTab({ fundCode }: Props) {
  const today = fmtLocal(new Date());

  // 설정일(inception) — 펀드 목록(useFunds)에서 해당 펀드 메타로 조회. "YYYY-MM-DD".
  const fundsQ = useFunds();
  const inceptionDate = useMemo(
    () => fundsQ.data?.data.find((f) => f.code === fundCode)?.inception ?? null,
    [fundsQ.data, fundCode],
  );

  // ---- 거래내역 기간 ----
  const [preset, setPreset] = useState<TxnPreset>("1M");
  const [customStart, setCustomStart] = useState<string>(fmtLocal(startOfMonth()));
  const [customEnd, setCustomEnd] = useState<string>(today);

  const { txnStart, txnEnd } = useMemo(() => {
    switch (preset) {
      case "MTD":
        return { txnStart: fmtLocal(startOfMonth()), txnEnd: today };
      case "1M":
        return { txnStart: fmtLocal(monthsAgo(1)), txnEnd: today };
      case "3M":
        return { txnStart: fmtLocal(monthsAgo(3)), txnEnd: today };
      case "6M":
        return { txnStart: fmtLocal(monthsAgo(6)), txnEnd: today };
      case "YTD":
        return { txnStart: fmtLocal(startOfYear()), txnEnd: today };
      case "since":
        // 설정일~현재. inception 미로드 시 매우 이른 날짜로 fallback(전체 포함).
        return { txnStart: inceptionDate ?? "2000-01-01", txnEnd: today };
      case "custom":
        return { txnStart: customStart, txnEnd: customEnd };
    }
  }, [preset, customStart, customEnd, today, inceptionDate]);

  const txnQ = useTransactions(fundCode, txnStart, txnEnd);

  // ---- 마스터 토글 (자산군↔종목) + 마스터 기간: 거래내역·비중추이·수익률 차트 공통 ----
  const [level, setLevel] = useState<WeightHistoryLevel>("asset");

  // ---- 영역차트: 기간은 마스터(거래내역 preset)와 공유 → chartStart/chartEnd = txnStart/txnEnd ----
  const [topNInput, setTopNInput] = useState<string>(""); // "" = 전체
  const [weightMode, setWeightMode] = useState<"pct" | "nav">("pct"); // 100%기준 / NAV기준
  const chartStart = txnStart;
  const chartEnd = txnEnd;

  const whQ = useWeightHistory(fundCode, chartStart, level, chartEnd);

  // ---- 세부내역 표 높이: 기본=요약 표 높이, 펼치기=전체 높이 ----
  const summaryBoxRef = useRef<HTMLDivElement>(null);
  const detailTableRef = useRef<HTMLTableElement>(null);
  const [summaryH, setSummaryH] = useState(0);
  const [detailFullH, setDetailFullH] = useState(0);
  const [detailExpanded, setDetailExpanded] = useState(false);
  const [detailAsset, setDetailAsset] = useState<string>(""); // "" = 전체

  const topN = useMemo(() => {
    const n = parseInt(topNInput, 10);
    return Number.isFinite(n) && n > 0 ? n : 0; // 0 = 전체
  }, [topNInput]);

  // ---- FX 포지션 (달러선물) ----
  const fxQ = useFxPosition(fundCode, chartStart, chartEnd);

  // ---- 종목별 수익률 ---- (start=chartStart → 편입이력(현재 미보유) 종목 하단 포함)
  const secQ = useSecurities(fundCode, chartStart);
  const allItems = useMemo(() => secQ.data?.items ?? [], [secQ.data]);
  const priceItems = useMemo(() => allItems.filter((it) => it.has_price), [allItems]);
  // 드롭다운 4그룹: 보유(가격O) / 보유(가격X·비중만) / 과거(가격O) / 과거(가격X)
  const held = (it: typeof allItems[number]) => it.currently_held !== false;
  const curPriced = useMemo(() => allItems.filter((it) => held(it) && it.has_price), [allItems]);
  const curNoPrice = useMemo(() => allItems.filter((it) => held(it) && !it.has_price), [allItems]);
  const pastPriced = useMemo(() => allItems.filter((it) => !held(it) && it.has_price), [allItems]);
  const pastNoPrice = useMemo(() => allItems.filter((it) => !held(it) && !it.has_price), [allItems]);
  // 수익률 차트 markup(구간 %변화율 측정) 모드 토글
  const [retMarkup, setRetMarkup] = useState(false);
  const [selItemCd, setSelItemCd] = useState<string>("");
  // 펀드 변경/목록 로드 시 기본 선택: 가격 있는 보유종목 중 비중 최상위(없으면 첫 종목).
  // 사용자가 가격 없는 종목을 골라도 유지되도록 allItems 기준으로만 리셋.
  useEffect(() => {
    if (allItems.length && !allItems.some((it) => it.item_cd === selItemCd)) {
      const pool = priceItems.length ? priceItems : allItems;
      const top = pool.reduce((a, b) => (b.weight > a.weight ? b : a));
      setSelItemCd(top.item_cd);
    }
    if (!allItems.length) setSelItemCd("");
  }, [allItems, priceItems, selItemCd]);
  const selItem = allItems.find((it) => it.item_cd === selItemCd);
  const secRetQ = useSecurityReturn(
    fundCode, selItemCd, selItem?.item_nm ?? "", chartStart, chartEnd,
  );

  // ---- 자산군 수익률 (자산군 모드): 일별 비중×종목가격 바스켓 지수 ----
  // "전체"(펀드 NAV 수익지수+설정/해지 현금흐름) 최상단 + 유동성 포함(가격 없으면 비중만).
  const assetKeys = useMemo(
    () => (level === "asset" ? ["전체", ...(whQ.data?.keys ?? [])] : []),
    [level, whQ.data],
  );
  const [selAsset, setSelAsset] = useState<string>("");
  useEffect(() => {
    if (assetKeys.length && !assetKeys.includes(selAsset)) setSelAsset(assetKeys[0]);
    if (!assetKeys.length && level === "asset") setSelAsset("");
  }, [assetKeys, selAsset, level]);
  const assetRetQ = useAssetClassReturn(
    fundCode, level === "asset" ? selAsset : "", chartStart, chartEnd,
  );

  // ---- 거래내역 집계/정렬 ----
  const txnRows = txnQ.data?.rows ?? [];
  const sortedRows = useMemo(
    () =>
      [...txnRows].sort((a, b) => {
        if (a.date !== b.date) return b.date < a.date ? -1 : 1; // 최신 우선
        if (a.fund_code !== b.fund_code) return a.fund_code < b.fund_code ? -1 : 1;
        return a.item_nm < b.item_nm ? -1 : 1;
      }),
    [txnRows],
  );
  const { buySum, sellSum } = useMemo(() => {
    let buy = 0, sell = 0;
    for (const r of txnRows) {
      if (r.side === "매수") buy += r.amount_eok;
      else if (r.side === "매도") sell += r.amount_eok;
    }
    return { buySum: buy, sellSum: sell };
  }, [txnRows]);
  const net = buySum - sellSum;

  // 종목별/자산군별 매수·매도·순매수 (기간 합계) — 마스터 토글 기준.
  const txnSummary = useMemo(() => {
    const map = new Map<string, { asset: string; buy: number; sell: number }>();
    for (const r of txnRows) {
      const key = level === "asset" ? r.asset_class : r.item_nm;
      const cur = map.get(key) ?? { asset: r.asset_class, buy: 0, sell: 0 };
      if (r.side === "매수") cur.buy += r.amount_eok;
      else if (r.side === "매도") cur.sell += r.amount_eok;
      map.set(key, cur);
    }
    return [...map.entries()]
      .map(([key, v]) => ({ key, asset: v.asset, buy: v.buy, sell: v.sell, net: v.buy - v.sell }))
      .filter((g) => g.buy !== 0 || g.sell !== 0)
      .sort((a, b) => {
        const oa = ASSET_ORDER[a.asset] ?? 99;
        const ob = ASSET_ORDER[b.asset] ?? 99;
        if (oa !== ob) return oa - ob;
        return b.net - a.net; // 자산군 내 순매수 내림차순
      });
  }, [txnRows, level]);

  // 세부내역 자산군 필터: 옵션(자산군순) + 필터 적용 행.
  const detailAssetOptions = useMemo(() => {
    const set = new Set(txnRows.map((r) => r.asset_class));
    return [...set].sort((a, b) => (ASSET_ORDER[a] ?? 99) - (ASSET_ORDER[b] ?? 99));
  }, [txnRows]);
  useEffect(() => {
    if (detailAsset && !detailAssetOptions.includes(detailAsset)) setDetailAsset("");
  }, [detailAssetOptions, detailAsset]);
  const filteredDetailRows = useMemo(
    () => (detailAsset ? sortedRows.filter((r) => r.asset_class === detailAsset) : sortedRows),
    [sortedRows, detailAsset],
  );

  // 세부내역 = 거래 + 펀드 설정/해지 현금흐름(자산군 필터 없을 때만). 날짜 내림차순 병합.
  // 설정/해지는 자산군 무관(부모펀드 자금 유출입)이라 자산군 필터 적용 시 제외.
  type DetailEntry = {
    date: string; fund_code: string; asset_class: string;
    item_nm: string; side: string; amount_eok: number; kind: "trade" | "cashflow";
  };
  const detailEntries = useMemo<DetailEntry[]>(() => {
    const tr: DetailEntry[] = filteredDetailRows.map((r) => ({
      date: r.date, fund_code: r.fund_code, asset_class: r.asset_class,
      item_nm: r.item_nm, side: r.side, amount_eok: r.amount_eok, kind: "trade",
    }));
    const cf: DetailEntry[] = detailAsset
      ? []
      : (txnQ.data?.cashflows ?? []).map((c) => ({
          date: c.date.replace(/-/g, ""), fund_code: fundCode, asset_class: "설정/해지",
          item_nm: c.side === "설정" ? "펀드 설정 (자금 유입)" : "펀드 해지 (자금 유출)",
          side: c.side, amount_eok: c.amount_eok, kind: "cashflow",
        }));
    return [...tr, ...cf].sort((a, b) => {
      const da = a.date.replace(/-/g, ""), db = b.date.replace(/-/g, "");
      if (da !== db) return db < da ? -1 : 1; // 최신 우선
      if (a.kind !== b.kind) return a.kind === "cashflow" ? -1 : 1; // 같은 날 현금흐름 먼저
      return a.item_nm < b.item_nm ? -1 : 1;
    });
  }, [filteredDetailRows, txnQ.data, detailAsset, fundCode]);

  // 요약 표 높이(좌) + 세부내역 표 전체 높이(우) 측정 — 데이터 변경 시 재측정.
  useLayoutEffect(() => {
    if (summaryBoxRef.current) setSummaryH(summaryBoxRef.current.offsetHeight);
    if (detailTableRef.current) setDetailFullH(detailTableRef.current.offsetHeight);
  }, [txnSummary, detailEntries, level]);

  // ---- 기간 전환 등으로 재계산이 길어질 때(>350ms) 로딩 플래시 ----
  // 설정후(inception~) 는 데이터가 많아 4~5초 걸려 → 빠른 전환엔 안 깜빡이게 디바운스.
  const anyFetching =
    txnQ.isFetching || whQ.isFetching || fxQ.isFetching ||
    secQ.isFetching || assetRetQ.isFetching || secRetQ.isFetching;
  const [showLoading, setShowLoading] = useState(false);
  useEffect(() => {
    if (!anyFetching) { setShowLoading(false); return; }
    const t = setTimeout(() => setShowLoading(true), 350);
    return () => clearTimeout(t);
  }, [anyFetching]);

  const isFofTxn = txnQ.data?.lookthrough_applied ?? false;
  const showFundCol = isFofTxn;
  const fmtD = (d: string) =>
    d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : d;

  return (
    <div className="tx-root">
      {showLoading && (
        <div className="tx-flash"><span className="tx-spin" />데이터 불러오는 중…</div>
      )}
      {/* ============ 컨트롤: 기준(자산군↔종목) + 기간 + 직접지정 ============ */}
      <div className="tx-card">
        <div className="tx-ctrl">
          <span className="lab">기준</span>
          <div className="tx-seg">
            {(["asset", "security"] as WeightHistoryLevel[]).map((lv) => (
              <button key={lv} className={level === lv ? "on" : ""} onClick={() => setLevel(lv)}>
                {lv === "asset" ? "자산군" : "종목"}
              </button>
            ))}
          </div>
          <span className="div" />
          <span className="lab">기간</span>
          {TXN_PRESETS.map((p) => (
            <button
              key={p.key}
              className={`tx-chip ${preset === p.key ? "on" : ""}`}
              onClick={() => setPreset(p.key)}
            >
              {p.label}
            </button>
          ))}
          {preset === "custom" && (
            <span className="tx-date">
              <input
                type="date" value={customStart} max={customEnd}
                onChange={(e) => setCustomStart(e.target.value)}
              />
              ~
              <input
                type="date" value={customEnd} min={customStart}
                onChange={(e) => setCustomEnd(e.target.value)}
              />
            </span>
          )}
        </div>
      </div>

      {/* ============ KPI 4카드 ============ */}
      <div className="tx-kpis">
        <div className="tx-kpi">
          <div className="k">매수</div>
          <div className="v num up">{buySum.toFixed(1)}<small>억</small></div>
          <div className="d">{txnStart} ~ {txnEnd}</div>
        </div>
        <div className="tx-kpi">
          <div className="k">매도</div>
          <div className="v num dn">{sellSum.toFixed(1)}<small>억</small></div>
          <div className="d">{txnRows.length}건</div>
        </div>
        <div className="tx-kpi">
          <div className="k">순매수</div>
          <div className={`v num ${net >= 0 ? "up" : "dn"}`}>
            {net >= 0 ? "+" : "−"}{Math.abs(net).toFixed(1)}<small>억</small>
          </div>
          <div className="d">{net >= 0 ? "순매수 우위" : "순매도 우위"}</div>
        </div>
        <div className="tx-kpi">
          <div className="k">거래 건수</div>
          <div className="v num">{txnRows.length}<small>건</small></div>
          <div className="d">{level === "asset" ? "자산군 기준" : "종목 기준"}</div>
        </div>
      </div>

      {/* ====================== 거래내역 ====================== */}
      <section className="tx-card tx-sec">
        <div className="tx-head">
          <h3>거래내역</h3>
          <div className="right tx-sub">
            {isFofTxn && (
              <span className="tx-fofnote">
                FoF: {(txnQ.data?.funds_queried ?? []).join(", ")} 거래 포함
              </span>
            )}
            <span>{txnStart} ~ {txnEnd}</span>
          </div>
        </div>
        <div className="tx-note">
          ※ 해외 종목 금액은 실제 USD 등 외화로 체결된 매매를 거래일 환율로 환산한 참고값
        </div>

        {txnQ.isLoading ? (
          <div className="tx-loading">로딩 중…</div>
        ) : sortedRows.length === 0 ? (
          <div className="tx-loading">해당 기간 거래내역 없음</div>
        ) : (
          <div className="tx-cols">
            {/* 좌: 자산군별/종목별 매수·매도·순매수 (기간 합계) */}
            <div>
              <div className="tx-coltitle">{level === "asset" ? "자산군별" : "종목별"} 매수·매도·순매수</div>
              <div ref={summaryBoxRef} className="tx-tblbox">
                <table className="tx-tbl">
                  <thead>
                    <tr>
                      <th className="l">자산군</th>
                      {level === "security" && <th className="l">종목명</th>}
                      <th>매수(억)</th>
                      <th>매도(억)</th>
                      <th>순매수(억)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {txnSummary.map((g) => (
                      <tr key={g.key}>
                        <td className="l">{g.asset}</td>
                        {level === "security" && <td className="l">{g.key}</td>}
                        <td className={`num ${g.buy ? "up" : "muted"}`}>{g.buy.toFixed(2)}</td>
                        <td className={`num ${g.sell ? "dn" : "muted"}`}>{g.sell.toFixed(2)}</td>
                        <td className={`num ${g.net > 0 ? "up" : g.net < 0 ? "dn" : "muted"}`} style={{ fontWeight: 600 }}>
                          {g.net >= 0 ? "+" : ""}{g.net.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                    <tr className="tot">
                      <td className="l" colSpan={level === "security" ? 2 : 1}>합계</td>
                      <td className="num up">{buySum.toFixed(2)}</td>
                      <td className="num dn">{sellSum.toFixed(2)}</td>
                      <td className={`num ${net >= 0 ? "up" : "dn"}`}>
                        {net >= 0 ? "+" : ""}{net.toFixed(2)}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            {/* 우: 세부내역 (일별 거래 상세, 날짜 내림차순) */}
            <div>
              <div className="tx-coltitle">
                세부내역 ({detailEntries.length}건)
                {!detailAsset && (txnQ.data?.cashflows?.length ?? 0) > 0 && (
                  <span className="muted" style={{ fontWeight: 400, marginLeft: 6 }}>
                    · 설정/해지 {txnQ.data?.cashflows?.length}건 포함
                  </span>
                )}
                <select className="tx-flt" value={detailAsset}
                  onChange={(e) => setDetailAsset(e.target.value)} title="자산군 필터">
                  <option value="">자산군 전체</option>
                  {detailAssetOptions.map((ac) => <option key={ac} value={ac}>{ac}</option>)}
                </select>
                <button className="tx-btn" onClick={() => setDetailExpanded((o) => !o)}>
                  {detailExpanded ? "접기" : "펼치기"}
                </button>
              </div>
              <div className="tx-scroll" style={{
                maxHeight: detailExpanded ? (detailFullH || undefined) : (summaryH || 420),
              }}>
                <table ref={detailTableRef} className="tx-tbl">
                  <thead className="sticky">
                    <tr>
                      <th className="l">날짜</th>
                      {showFundCol && <th>펀드</th>}
                      <th className="l">자산군</th>
                      <th className="l">종목명</th>
                      <th>매수/매도</th>
                      <th>금액(억)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailEntries.map((r, i) => (
                      <tr key={i} className={r.kind === "cashflow" ? "tx-cfrow" : undefined}>
                        <td className="l muted">{fmtD(r.date)}</td>
                        {showFundCol && <td>{r.fund_code}</td>}
                        <td className="l">{r.asset_class}</td>
                        <td className="l">{r.item_nm}</td>
                        <td className={sideClass(r.side)}>{r.side}</td>
                        <td className={`num ${sideClass(r.side)}`}>{r.amount_eok.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* ===== 일별 비중추이 + 수익률 차트 side-by-side ===== */}
      <div className="tx-chartrow">
        {/* 일별 비중 영역차트 */}
        <section className="tx-card tx-sec tx-chartcard">
          <div className="tx-head">
            <h3>일별 비중 추이</h3>
            <div className="right">
              {level === "security" && (
                <label className="tx-sub">
                  상위 N:&nbsp;
                  <input type="number" min={1} placeholder="전체" value={topNInput}
                    onChange={(e) => setTopNInput(e.target.value)} className="tx-numin" />
                  <span className="muted" style={{ marginLeft: 4 }}>
                    {topN > 0 ? `상위 ${topN} + 기타` : `전체 ${whQ.data?.keys.length ?? 0}`}
                  </span>
                </label>
              )}
              <div className="tx-seg" style={{ marginLeft: 8 }}>
                {(["pct", "nav"] as const).map((m) => (
                  <button key={m} className={weightMode === m ? "on" : ""}
                    onClick={() => setWeightMode(m)}>
                    {m === "pct" ? "100%기준" : "NAV기준"}
                  </button>
                ))}
              </div>
            </div>
          </div>
          {whQ.data?.lookthrough_applied && (
            <div className="tx-fofnote" style={{ marginBottom: 4 }}>FoF look-through: 자펀드 종목 편입비율 가중평균</div>
          )}
          <div className="tx-chartbody">
            {whQ.isLoading ? (
              <div className="tx-loading">로딩 중…</div>
            ) : (
              <WeightAreaChart
                points={whQ.data?.points ?? []}
                keys={whQ.data?.keys ?? []}
                level={level}
                topN={topN}
                markers={whQ.data?.markers ?? []}
                instanceKey={`${fundCode}-${level}-${preset}-${weightMode}`}
                xRange={[chartStart, chartEnd]}
                valueMode={weightMode}
                nav={whQ.data?.nav ?? []}
              />
            )}
          </div>
        </section>

        {/* 자산군/종목 수익률 + 매매 시점 */}
        <section className="tx-card tx-sec tx-chartcard">
          <div className="tx-head">
            <h3>{level === "asset" ? "자산군 수익률 · 매매 시점" : "종목 수익률 · 매매 시점"}</h3>
            <div className="right">
              {level === "security" ? (
                <select className="tx-flt" value={selItemCd} onChange={(e) => setSelItemCd(e.target.value)}>
                  {allItems.length === 0 && <option value="">종목 없음</option>}
                  {curPriced.map((it) => (
                    <option key={it.item_cd} value={it.item_cd}>
                      [{it.bucket}] {it.item_nm} ({it.weight.toFixed(1)}%)
                    </option>
                  ))}
                  {curNoPrice.length > 0 && (
                    <optgroup label="── 가격 없음 (비중만) ──">
                      {curNoPrice.map((it) => (
                        <option key={it.item_cd} value={it.item_cd}>
                          [{it.bucket}] {it.item_nm} ({it.weight.toFixed(1)}%)
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {pastPriced.length > 0 && (
                    <optgroup label="── 과거 편입 (현재 미보유) ──">
                      {pastPriced.map((it) => (
                        <option key={it.item_cd} value={it.item_cd}>
                          [{it.bucket}] {it.item_nm} · 과거
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {pastNoPrice.length > 0 && (
                    <optgroup label="── 과거 편입 · 가격 없음 (비중만) ──">
                      {pastNoPrice.map((it) => (
                        <option key={it.item_cd} value={it.item_cd}>
                          [{it.bucket}] {it.item_nm} · 과거
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              ) : (
                <select className="tx-flt" value={selAsset} onChange={(e) => setSelAsset(e.target.value)}>
                  {assetKeys.length === 0 && <option value="">자산군 없음</option>}
                  {assetKeys.map((k) => <option key={k} value={k}>{k === "전체" ? "펀드" : k}</option>)}
                </select>
              )}
              <button
                className={`tx-btn ${retMarkup ? "on" : ""}`}
                onClick={() => setRetMarkup((v) => !v)}
                title="드래그로 두 시점 사이 지수 변화율(%)을 표시. OFF 시 드래그=줌(y 자동보정)"
              >
                변화율 {retMarkup ? "ON" : "OFF"}
              </button>
            </div>
          </div>

          <div className="tx-chartbody">
            {level === "security" ? (
              !selItemCd ? (
                <div className="tx-loading">표시할 보유종목이 없습니다.</div>
              ) : secRetQ.isLoading ? (
                <div className="tx-loading">로딩 중…</div>
              ) : (
                <SecurityReturnChart
                  points={secRetQ.data?.points ?? []}
                  trades={secRetQ.data?.trades ?? []}
                  weights={secRetQ.data?.weights ?? []}
                  itemNm={selItem?.item_nm ?? ""}
                  instanceKey={`${fundCode}-${selItemCd}-${preset}`}
                  xRange={[chartStart, chartEnd]}
                  markupMode={retMarkup}
                />
              )
            ) : !selAsset ? (
              <div className="tx-loading">표시할 자산군이 없습니다.</div>
            ) : assetRetQ.isLoading ? (
              <div className="tx-loading">로딩 중…</div>
            ) : (
              <SecurityReturnChart
                points={assetRetQ.data?.points ?? []}
                trades={assetRetQ.data?.trades ?? []}
                weights={assetRetQ.data?.weights ?? []}
                weightComponents={assetRetQ.data?.weight_components ?? []}
                tradeComponents={assetRetQ.data?.trade_components ?? []}
                itemNm={selAsset === "전체" ? "펀드" : selAsset}
                instanceKey={`${fundCode}-asset-${selAsset}-${preset}`}
                xRange={[chartStart, chartEnd]}
                markupMode={retMarkup}
                navMode={selAsset === "전체"}
              />
            )}
          </div>
        </section>
      </div>

      {/* ====================== FX 포지션 (달러선물) ====================== */}
      {fxQ.data?.has_fx && (
        <section className="tx-card tx-sec">
          <div className="tx-head"><h3>FX 포지션 (달러선물)</h3></div>
          <div className="tx-chartrow">
            <div>
              <div className="tx-note">
                환헤지 순비중(% NAV, 매도=양수) · 해외자산 비중(해외주식+해외채권+외화예금) · 점선 = 월물 롤오버
              </div>
              <FxPositionChart
                points={fxQ.data.points}
                keys={fxQ.data.keys}
                foreignWeight={fxQ.data.foreign_weight}
                instanceKey={`${fundCode}-fx-${preset}`}
              />
            </div>
            <div>
              <div className="tx-note">
                헤지갭(해외자산비중 − FX순비중) · 우축 USD/KRW · 빨간 점선 = 가이드상한
                (FX매도 ≤ 해외자산비중+10%, 갭 −10%p 미만 시 위배)
              </div>
              <FxHedgeGapChart
                points={fxQ.data.points}
                foreignWeight={fxQ.data.foreign_weight}
                usdkrw={fxQ.data.usdkrw}
                instanceKey={`${fundCode}-fxgap-${preset}`}
              />
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
