import { useEffect, useMemo, useState } from "react";
import { useOverview } from "../hooks/useOverview";
import { usePeriodReturns } from "../hooks/usePeriodReturns";
import NavChart from "../components/charts/NavChart";
import LoadingBar from "../components/common/LoadingBar";

interface Props {
  fundCode: string;
}

type RetMode = "SI" | "YTD";

// 기간별 수익률 표 컬럼. MTD/YTD 시작일=전월말/전년말 영업일(전산 일치, 백엔드 _calc_ref_dates).
const PERIOD_COLS: [string, string][] = [
  ["MTD", "MTD"], ["1M", "1M"], ["3M", "3M"], ["6M", "6M"], ["1Y", "1Y"], ["YTD", "YTD"], ["SI", "설정후"],
];

// ---------- 포맷 ----------
const pct = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(2)}%`;
const pctSigned = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;
const pctpSigned = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(2)}%p`;
// 원 → 억 (콤마)
const eok = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${Math.round(v / 1e8).toLocaleString()}억`;
const sign = (v: number | null | undefined) => (v != null && v >= 0 ? "pos" : "neg");
const daysBetween = (aIso: string, bIso: string) =>
  (Date.parse(bIso) - Date.parse(aIso)) / 86_400_000;

export default function OverviewTab({ fundCode }: Props) {
  const { data, isLoading, error } = useOverview(fundCode);

  const [retMode, setRetMode] = useState<RetMode>("SI");
  // 비교선 토글: 목표/벤치(SAA/BM) 독립 ON/OFF — 둘 다 켜거나 둘 다 끌 수 있음 (2026-07-03 사용자 지정).
  const [benchOn, setBenchOn] = useState(true);
  const [targetOn, setTargetOn] = useState(false);
  // 연환산 표시 토글 — ON 시 수익률 카드·차트 pcards 를 연환산 값으로 전환 (2026-07-07)
  const [annualize, setAnnualize] = useState(false);

  // 조회기간(날짜 윈도우) — 기본 전체 구간(설정후). 펀드 변경 시 리셋.
  const series = data?.nav_series ?? [];
  const fullStart = series[0]?.date ?? "";
  const fullEnd = series.length ? series[series.length - 1].date : "";
  const [start, setStart] = useState(fullStart);
  const [end, setEnd] = useState(fullEnd);
  useEffect(() => {
    setStart(fullStart);
    setEnd(fullEnd);
    setRetMode("SI");
    // 디폴트: 목표 있는 BM-less 펀드는 목표만 ON, 아니면 벤치(SAA/BM)만 ON
    const ht = data?.benchmark_kind === "SAA" && data?.fund_meta?.target_return_annual != null;
    setTargetOn(!!ht);
    setBenchOn(!ht);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fundCode, fullStart, fullEnd]);

  const sliced = useMemo(
    () => series.filter((p) => p.date >= start && p.date <= end),
    [series, start, end],
  );

  // 기간별 수익률 표 — 조회 종료일 앵커 트레일링 수익률 (2026-07-03 사용자 지정).
  // 종료일=전체 끝(기본)이면 최신 영업일 앵커(백엔드 기본)와 동일해 파라미터 생략.
  const prq = usePeriodReturns(fundCode, end && end !== fullEnd ? end : undefined);

  if (isLoading) return <LoadingBar label="loading overview..." />;
  if (error || !data) return <div style={{ color: "#dc2626" }}>failed to load overview</div>;

  const fm = data.fund_meta;
  const benchKind = data.benchmark_kind;
  const benchLabel = data.benchmark_label ?? (benchKind === "BM" ? "BM" : "SAA");
  const hasBench = benchKind !== "none";
  const target = fm?.target_return_annual ?? null;
  // 07G04 등 BM 펀드는 목표를 메타바에만 표기 → 차트/카드 목표선은 SAA 펀드 전용.
  const hasTarget = benchKind === "SAA" && target != null;
  const benchActive = benchOn && hasBench;
  const targetActive = targetOn && hasTarget;

  const pr = data.period_returns ?? {};
  const bmpr = data.bm_period_returns ?? {};
  const asof = data.meta.as_of_date ?? null;
  const inception = fm?.inception ?? null;

  // 기간별 수익률 표 데이터 — 조회 종료일 앵커 (지표카드는 최신 as_of 기준 유지)
  const tpr = prq.data?.period_returns ?? pr;
  const tbmpr = prq.data?.bm_period_returns ?? bmpr;
  const tEnd = prq.data?.end_date ?? asof;
  // 벤치마크 적재 지연 여부 — 지연 시 백엔드가 수익률 앵커를 BM 최종일로 당긴다.
  // ★ 여기서 returns_as_of < asof 를 직접 비교하면 안 된다: 기준가는 주말 행도
  // 적재돼(보수 일할만 반영) 주말·월요일마다 오탐이 뜬다. 영업일 판정은 백엔드가 한다.
  const returnsAsOf = data.returns_as_of ?? asof;
  const bmLag = !!data.bm_lag;

  // 목표 누적수익률 (기간별 일수 환산). anchor 미지정 시 최신 as_of, 표는 조회 종료일 앵커.
  const TARGET_DAYS: Record<string, number> = { "1W": 7, "1M": 30.44, "3M": 91.31, "6M": 182.62, "1Y": 365.25 };
  const targetForPeriod = (k: string, anchor: string | null = asof): number | null => {
    if (target == null || !anchor) return null;
    let days: number;
    if (k === "SI") days = inception ? daysBetween(inception, anchor) : NaN;
    else if (k === "YTD") {
      const jan1 = `${anchor.slice(0, 4)}-01-01`;
      days = daysBetween(inception && inception > jan1 ? inception : jan1, anchor);
    } else if (k === "MTD") days = Number(anchor.slice(8, 10)); // 전월말 대비 경과일 근사
    else days = TARGET_DAYS[k];
    if (!Number.isFinite(days)) return null;
    return Math.pow(1 + target, Math.max(days, 0) / 365) - 1;
  };
  // 수익률 카드 비교값 — 벤치 ON 우선, 아니면 목표 ON, 둘 다 OFF면 비교 생략
  const baseForPeriod = (k: string): number | null =>
    benchActive ? bmpr[k] ?? null : targetActive ? targetForPeriod(k) : null;
  const baseLabel = benchActive ? benchLabel : "목표";

  // 연환산 — R v3 동일 공식 (1+기간수익률)^(365.25/일수) - 1
  const annualizeBy = (r: number | null, days: number | null): number | null =>
    r == null || days == null || days <= 0 || r <= -1 ? null : Math.pow(1 + r, 365.25 / days) - 1;
  const periodDaysOf = (k: string, anchor: string | null = asof): number | null => {
    if (!anchor) return null;
    if (k === "SI") return inception ? Math.max(daysBetween(inception, anchor), 1) : null;
    if (k === "YTD") return Math.max(daysBetween(`${anchor.slice(0, 4)}-01-01`, anchor), 1);
    if (k === "MTD") return Math.max(Number(anchor.slice(8, 10)), 1);
    return TARGET_DAYS[k] ?? null;
  };
  // 기간별 표 셀 값 — 연환산 ON 시 tEnd 앵커 일수로 연환산
  const tv = (r: number | null | undefined, k: string): number | null =>
    annualize ? annualizeBy(r ?? null, periodDaysOf(k, tEnd)) : r ?? null;

  // 지표카드 데이터
  const navPrice = fm?.nav ?? series[series.length - 1]?.nav ?? null;
  const last = series[series.length - 1];
  const prev = series[series.length - 2];
  const prevDelta =
    last && prev && prev.nav ? { abs: last.nav - prev.nav, pct: last.nav / prev.nav - 1 } : null;
  // 순자산 카드 = 현재 순자산(최신 NAST = nav_series 마지막 aum). 설정액(메타)과 구분.
  const navTotal = series[series.length - 1]?.aum ?? null;
  // 변동성 — 수익률 토글(retMode)과 동기화: 설정후=누적, YTD=YTD
  const portVol = retMode === "SI" ? data.cards.find((c) => c.key === "vol")?.value ?? null : data.volatility_ytd ?? null;
  const benchVol = retMode === "SI" ? data.bm_volatility ?? null : data.bm_volatility_ytd ?? null;
  // 주식비중 (포트 look-through vs 벤치)
  const eqW = data.equity_weight ?? null;
  const bmEqW = data.bm_equity_weight ?? null;
  const eqDiff = eqW != null && bmEqW != null ? eqW - bmEqW : null;

  // 수익률 카드(설정후/YTD 토글) — 활성 기준선 대비. 연환산 ON 시 연환산 값으로 전환.
  const portRet = pr[retMode] ?? null;
  const baseRet = baseForPeriod(retMode);
  const portRetD = annualize ? annualizeBy(portRet, periodDaysOf(retMode)) : portRet;
  const baseRetD = annualize
    ? (benchActive ? annualizeBy(baseRet, periodDaysOf(retMode)) : baseRet != null ? target : null)
    : baseRet;
  const baseDeltaD = portRetD != null && baseRetD != null ? portRetD - baseRetD : null;

  // 차트 윈도우(pcards) 수익률
  const wf = sliced[0];
  const wl = sliced[sliced.length - 1];
  const winDays = wf && wl ? Math.max(daysBetween(wf.date, wl.date), 1) : null;
  const annWin = (r: number | null) => annualizeBy(r, winDays);
  const winPort = sliced.length >= 2 && wf?.nav ? wl.nav / wf.nav - 1 : null;
  const winBench =
    hasBench && wf?.bm != null && wl?.bm != null && wf.bm ? wl.bm / wf.bm - 1 : null;
  const winTarget =
    target != null && wf && wl ? Math.pow(1 + target, Math.max(daysBetween(wf.date, wl.date), 0) / 365) - 1 : null;

  // 프리셋 (윈도우 시작일 변경)
  const applyPreset = (p: "MTD" | "QTD" | "YTD" | "SI") => {
    if (!asof) return;
    let s = fullStart;
    if (p === "MTD") s = `${asof.slice(0, 7)}-01`;
    else if (p === "YTD") s = `${asof.slice(0, 4)}-01-01`;
    else if (p === "QTD") {
      const m = Number(asof.slice(5, 7));
      const qm = m - ((m - 1) % 3);
      s = `${asof.slice(0, 4)}-${String(qm).padStart(2, "0")}-01`;
    }
    if (s < fullStart) s = fullStart;
    setStart(s);
    setEnd(fullEnd);
  };
  const activePreset = (() => {
    if (start === fullStart) return "SI";
    if (asof && start === `${asof.slice(0, 4)}-01-01`) return "YTD";
    if (asof && start === `${asof.slice(0, 7)}-01`) return "MTD";
    return null;
  })();

  const metaRows = [
    { k: "코드", v: data.fund_code, num: true },
    { k: "표준코드", v: fm?.ticker ?? "—", num: true },
    { k: "펀드타입", v: fm?.fund_type ?? "—" },
    { k: "수익자", v: fm?.beneficiary ?? "—" },
    { k: "운용사", v: fm?.manager ?? "—" },
    { k: "총보수", v: fm?.fee_bp != null ? `${fm.fee_bp}bp` : "—", num: true },
  ];

  return (
    <section className="ov-root">
      {/* 헤더 — 목표 있는 펀드는 타이틀 우측에 목표수익률 노출 */}
      <div className="ov-head">
        <h2 className="fund-title">
          {data.fund_name} <span className="code">{data.fund_code}</span>
        </h2>
        {/* 목표수익률 카드는 차트 패널 pcards(BM 우측)로 이동 — 타이틀 행 높이 통일 (2026-07-07) */}
      </div>

      {/* 메타바 */}
      <div className="ov-meta">
        {metaRows.map((it) => (
          <div key={it.k}>
            <div className="k">{it.k}</div>
            <div className={`v ${it.num ? "num" : ""}`}>{it.v}</div>
          </div>
        ))}
      </div>

      {/* 지표카드 — 필드명(좌)+값(우) 한 줄 */}
      <div className="ov-stats">
        {/* 기준일자 */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">기준일자</span>
            <span className="val num date">{asof ?? "—"}</span>
          </div>
          <div className="cmp">설정일 <span className="num">{inception ?? "—"}</span></div>
        </div>

        {/* 기준가 */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">기준가</span>
            <span className="val num">{navPrice != null ? navPrice.toFixed(2) : "—"}</span>
          </div>
          <div className="cmp">
            전일대비{" "}
            {prevDelta ? (
              <span className={`${sign(prevDelta.abs)} num`}>
                {prevDelta.abs >= 0 ? "▲" : "▼"} {Math.abs(prevDelta.abs).toFixed(2)} ({pctSigned(prevDelta.pct)})
              </span>
            ) : <span className="num">—</span>}
          </div>
        </div>

        {/* 순자산 */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">순자산 (NAV)</span>
            <span className="val num">{eok(navTotal)}</span>
          </div>
          <div className="cmp">
            설정액 <span className="num">{eok(fm?.setup_amount)}</span>
          </div>
        </div>

        {/* 수익률 (설정후/YTD 토글, 연환산 토글 연동) */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">수익률{annualize ? <span className="sub"> 연환산</span> : null}</span>
            <div className="ov-ctoggle">
              <button type="button" className={retMode === "SI" ? "on" : ""} onClick={() => setRetMode("SI")}>설정후</button>
              <button type="button" className={retMode === "YTD" ? "on" : ""} onClick={() => setRetMode("YTD")}>YTD</button>
            </div>
            <span className={`val num ${sign(portRetD)}`}>{pctSigned(portRetD)}</span>
          </div>
          <div className="cmp">
            {benchActive || targetActive ? (
              <>
                {baseLabel} <span className="num">{pct(baseRetD)}</span>{" "}
                {baseDeltaD != null && <span className={`delta ${sign(baseDeltaD)} num`}>({pctpSigned(baseDeltaD)})</span>}
              </>
            ) : <span className="num">{" "}</span>}
          </div>
          {/* 07G07: SI 분모 앵커(편입일) 안내 — 07G07만, 설정후 모드에서만 (2026-07-13 사용자 지정) */}
          {fundCode === "07G07" && retMode === "SI" && (
            <div className="cmp"><span className="num">20220104</span> 설정</div>
          )}
        </div>

        {/* 변동성 (수익률과 동기화된 설정후/YTD 토글) */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">변동성 <span className="ov-info" title="주간수익률 표준편차 × √52 (연환산). 설정후=설정일 이후 누적, YTD=연초 이후 — 위 수익률 토글과 연동. 아랫줄은 벤치마크 변동성과 차이(%p)">i</span></span>
            <div className="ov-ctoggle">
              <button type="button" className={retMode === "SI" ? "on" : ""} onClick={() => setRetMode("SI")}>설정후</button>
              <button type="button" className={retMode === "YTD" ? "on" : ""} onClick={() => setRetMode("YTD")}>YTD</button>
            </div>
            <span className="val num">{pct(portVol)}</span>
          </div>
          <div className="cmp">
            {benchActive && benchVol != null ? (
              <>
                {benchLabel} <span className="num">{pct(benchVol)}</span> ·{" "}
                <span className={`delta ${sign(portVol != null ? portVol - benchVol : null)} num`}>
                  {pctpSigned(portVol != null ? portVol - benchVol : null)}
                </span>
              </>
            ) : <span className="num">{" "}</span>}
          </div>
        </div>

        {/* 주식비중 (포트 vs 벤치) */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">주식비중</span>
            <span className="val num">{pct(eqW)}</span>
          </div>
          <div className="cmp">
            {benchActive && bmEqW != null ? (
              <>
                {benchLabel} <span className="num">{pct(bmEqW)}</span>{" "}
                <span className={`delta ${sign(eqDiff)} num`}>{pctpSigned(eqDiff)}</span>
              </>
            ) : <span className="num">{" "}</span>}
          </div>
        </div>
      </div>

      {/* 차트 카드 */}
      <div className="ov-card">
        <div className="ov-toolbar">
          <div className="ov-field">
            <label>시작</label>
            <input type="date" value={start} min={fullStart} max={end} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="ov-field">
            <label>종료</label>
            <input type="date" value={end} min={start} max={fullEnd} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div className="ov-field">
            <label>기간</label>
            <div className="ov-presets">
              {(["MTD", "QTD", "YTD", "SI"] as const).map((p) => (
                <button key={p} type="button" className={activePreset === p ? "on" : ""} onClick={() => applyPreset(p)}>
                  {p === "SI" ? "설정후" : p}
                </button>
              ))}
            </div>
          </div>
          {/* 연환산 토글 — ON 시 pcards·상단 수익률 카드 연환산 (2026-07-07) */}
          <div className="ov-field">
            <label>연환산</label>
            <div className="ov-presets">
              <button type="button" className={annualize ? "on" : ""} onClick={() => setAnnualize((v) => !v)}>
                {annualize ? "ON" : "OFF"}
              </button>
            </div>
          </div>
          <div className="ov-pcards">
            <div className="ov-pcard">
              <div className="k">포트</div>
              {/* 괄호 병기 제거 — 연환산 토글로 전환 (2026-07-07 사용자 지정) */}
              <div className={`v num ${sign(winPort)}`}>{pctSigned(annualize ? annWin(winPort) : winPort)}</div>
            </div>
            {hasBench && (
              <div className={`ov-pcard saa ${benchOn ? "sel" : "off"}`} onClick={() => setBenchOn((v) => !v)}>
                <div className="k">{benchLabel}<span className="tag">{benchOn ? "ON" : "OFF"}</span></div>
                <div className="v num">{pctSigned(annualize ? annWin(winBench) : winBench)}</div>
              </div>
            )}
            {/* 목표수익률 — 목표 있는 펀드 전부 표시 (07G04 등 BM 펀드 포함, 구 헤더 카드 대체).
                차트 목표선 토글은 기존 규약대로 SAA 펀드(hasTarget)만. */}
            {target != null && (
              <div
                className={`ov-pcard goal ${hasTarget ? (targetOn ? "sel" : "off") : ""}`}
                onClick={hasTarget ? () => setTargetOn((v) => !v) : undefined}
                style={hasTarget ? undefined : { cursor: "default" }}
              >
                <div className="k">목표수익률{hasTarget ? <span className="tag">{targetOn ? "ON" : "OFF"}</span> : null}</div>
                <div className="v num">
                  {annualize ? `연 ${pct(target)}` : pctSigned(winTarget)}
                  <span className="sub num">
                    {annualize ? ` (기간 ${pctSigned(winTarget)})` : ` (연 ${pct(target)})`}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="ov-chartwrap">
          <NavChart
            points={sliced}
            benchmarkKind={benchKind}
            benchmarkLabel={benchLabel}
            showBm={benchActive}
            showTarget={targetActive}
            targetAnnual={target}
            inceptionDate={inception ?? undefined}
            instanceKey={`${fundCode}-${start}-${end}-${sliced.length}`}
          />
        </div>

        {/* 기간별 수익률 표 (성과분석 탭과 동일 양식) — 조회 종료일 앵커, 차트 하단 */}
        <div className="ov-ptbl">
          <div className="t">
            기간별 수익률{annualize ? " (연환산)" : ""}{tEnd ? <span style={{ fontWeight: 400, color: "#9ca3af", marginLeft: 6 }}>(기준 {tEnd})</span> : null}
            {prq.isFetching && <span className="bn-tag recalc" style={{ marginLeft: 8 }}>● 계산 중…</span>}
          </div>
          {/* 벤치마크 미적재일 — 펀드/BM 기간을 BM 최종일로 맞춰 계산(초과수익 왜곡 방지) */}
          {bmLag && (
            <div style={{ fontSize: 11, color: "#b45309", marginBottom: 6 }}>
              ⚠ 벤치마크 미적재 — 수익률은 BM 최종일({returnsAsOf}) 기준, 기준가·AUM 은 최신({asof}) 기준
            </div>
          )}
          {(data.bm_source_notes ?? []).length > 0 && (
            <div style={{ fontSize: 11, color: "#b45309", marginBottom: 6 }}>
              ⚠ BM 구성지수 소스: {(data.bm_source_notes ?? []).join(" · ")}
            </div>
          )}
          <table className="ov-tbl">
            <thead>
              <tr>
                <th>구분</th>
                {PERIOD_COLS.map(([k, label]) => <th key={k} className="r">{label}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>AP 수익률</td>
                {PERIOD_COLS.map(([k]) => {
                  const v = tv(tpr[k], k);
                  return <td key={k} className={`r num ${v != null ? sign(v) : ""}`}>{v != null ? pctSigned(v) : "—"}</td>;
                })}
              </tr>
              {/* 켜진 비교선(벤치/목표)만 표에 반영 — 둘 다 OFF면 AP 행만 (2026-07-03 사용자 지정) */}
              {benchActive && (
                <tr>
                  <td>{benchLabel} 수익률</td>
                  {PERIOD_COLS.map(([k]) => {
                    const v = tv(tbmpr[k], k);
                    return <td key={k} className={`r num ${v != null ? sign(v) : ""}`}>{v != null ? pctSigned(v) : "—"}</td>;
                  })}
                </tr>
              )}
              {benchActive && (
                <tr>
                  <td>초과</td>
                  {PERIOD_COLS.map(([k]) => {
                    const a = tv(tpr[k], k); const b = tv(tbmpr[k], k);
                    const ex = a != null && b != null ? a - b : null;
                    return <td key={k} className={`r num b ${ex != null ? sign(ex) : ""}`}>{ex != null ? pctSigned(ex) : "—"}</td>;
                  })}
                </tr>
              )}
              {targetActive && (
                <tr>
                  <td>목표 수익률</td>
                  {PERIOD_COLS.map(([k]) => {
                    const v = annualize ? target : targetForPeriod(k, tEnd);
                    return <td key={k} className={`r num ${v != null ? sign(v) : ""}`}>{v != null ? pctSigned(v) : "—"}</td>;
                  })}
                </tr>
              )}
              {targetActive && (
                <tr>
                  <td>목표대비</td>
                  {PERIOD_COLS.map(([k]) => {
                    const a = tv(tpr[k], k);
                    const t = annualize ? target : targetForPeriod(k, tEnd);
                    const ex = a != null && t != null ? a - t : null;
                    return <td key={k} className={`r num b ${ex != null ? sign(ex) : ""}`}>{ex != null ? pctSigned(ex) : "—"}</td>;
                  })}
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
