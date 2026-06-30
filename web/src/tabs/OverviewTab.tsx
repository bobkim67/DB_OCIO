import { useEffect, useMemo, useState } from "react";
import { useOverview } from "../hooks/useOverview";
import NavChart from "../components/charts/NavChart";
import LoadingBar from "../components/common/LoadingBar";

interface Props {
  fundCode: string;
}

type RetMode = "SI" | "YTD";

// 기간별 수익률 표 컬럼 (성과분석 탭과 동일 양식)
const PERIOD_COLS: [string, string][] = [
  ["1M", "1M"], ["3M", "3M"], ["6M", "6M"], ["1Y", "1Y"], ["YTD", "YTD"], ["SI", "설정후"],
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
  // 비교 기준선: 목표(target) vs 벤치(SAA/BM) — 차트 pcard 에서 둘 중 하나만 ON.
  const [baseMode, setBaseMode] = useState<"target" | "bench">("bench");

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
    // 목표 있는 BM-less 펀드는 목표 기준 디폴트, 아니면 벤치(SAA/BM) 기준
    const ht = data?.benchmark_kind === "SAA" && data?.fund_meta?.target_return_annual != null;
    setBaseMode(ht ? "target" : "bench");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fundCode, fullStart, fullEnd]);

  const sliced = useMemo(
    () => series.filter((p) => p.date >= start && p.date <= end),
    [series, start, end],
  );

  if (isLoading) return <LoadingBar label="loading overview..." />;
  if (error || !data) return <div style={{ color: "#dc2626" }}>failed to load overview</div>;

  const fm = data.fund_meta;
  const benchKind = data.benchmark_kind;
  const benchLabel = data.benchmark_label ?? (benchKind === "BM" ? "BM" : "SAA");
  const hasBench = benchKind !== "none";
  const target = fm?.target_return_annual ?? null;
  // 07G04 등 BM 펀드는 목표를 메타바에만 표기 → 차트/카드 목표선은 SAA 펀드 전용.
  const hasTarget = benchKind === "SAA" && target != null;
  const baseIsTarget = baseMode === "target" && hasTarget;
  const baseLabel = baseIsTarget ? "목표" : benchLabel;

  const pr = data.period_returns ?? {};
  const bmpr = data.bm_period_returns ?? {};
  const asof = data.meta.as_of_date ?? null;
  const inception = fm?.inception ?? null;

  // 목표 누적수익률 (기간별 일수 환산)
  const TARGET_DAYS: Record<string, number> = { "1W": 7, "1M": 30.44, "3M": 91.31, "6M": 182.62 };
  const targetForPeriod = (k: string): number | null => {
    if (target == null || !asof) return null;
    let days: number;
    if (k === "SI") days = inception ? daysBetween(inception, asof) : NaN;
    else if (k === "YTD") {
      const jan1 = `${asof.slice(0, 4)}-01-01`;
      days = daysBetween(inception && inception > jan1 ? inception : jan1, asof);
    } else days = TARGET_DAYS[k];
    if (!Number.isFinite(days)) return null;
    return Math.pow(1 + target, Math.max(days, 0) / 365) - 1;
  };
  // 활성 기준선(목표 or 벤치)의 기간별 값
  const baseForPeriod = (k: string): number | null =>
    baseIsTarget ? targetForPeriod(k) : bmpr[k] ?? null;

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

  // 수익률 카드(설정후/YTD 토글) — 활성 기준선 대비
  const portRet = pr[retMode] ?? null;
  const baseRet = baseForPeriod(retMode);
  const baseDelta = portRet != null && baseRet != null ? portRet - baseRet : null;

  // 차트 윈도우(pcards) 수익률
  const wf = sliced[0];
  const wl = sliced[sliced.length - 1];
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
        <h1>
          {data.fund_name} <span className="code">{data.fund_code}</span>
        </h1>
        {target != null && (
          <div className="ov-target-card">
            <div className="k">목표수익률</div>
            <div className="v num">연 {(target * 100).toFixed(1)}%</div>
          </div>
        )}
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

        {/* 수익률 (설정후/YTD 토글) */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">수익률</span>
            <div className="ov-ctoggle">
              <button type="button" className={retMode === "SI" ? "on" : ""} onClick={() => setRetMode("SI")}>설정후</button>
              <button type="button" className={retMode === "YTD" ? "on" : ""} onClick={() => setRetMode("YTD")}>YTD</button>
            </div>
            <span className={`val num ${sign(portRet)}`}>{pctSigned(portRet)}</span>
          </div>
          <div className="cmp">
            {baseIsTarget || hasBench ? (
              <>
                {baseLabel} <span className="num">{pct(baseRet)}</span>{" "}
                {baseDelta != null && <span className={`delta ${sign(baseDelta)} num`}>({pctpSigned(baseDelta)})</span>}
              </>
            ) : <span className="num">{" "}</span>}
          </div>
        </div>

        {/* 변동성 (수익률과 동기화된 설정후/YTD 토글) */}
        <div className="ov-stat">
          <div className="ov-stat-top">
            <span className="label">변동성</span>
            <div className="ov-ctoggle">
              <button type="button" className={retMode === "SI" ? "on" : ""} onClick={() => setRetMode("SI")}>설정후</button>
              <button type="button" className={retMode === "YTD" ? "on" : ""} onClick={() => setRetMode("YTD")}>YTD</button>
            </div>
            <span className="val num">{pct(portVol)}</span>
          </div>
          <div className="cmp">
            {!baseIsTarget && hasBench && benchVol != null ? (
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
            {!baseIsTarget && hasBench && bmEqW != null ? (
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
          <div className="ov-pcards">
            <div className="ov-pcard">
              <div className="k">포트</div>
              <div className={`v num ${sign(winPort)}`}>{pctSigned(winPort)}</div>
            </div>
            {hasTarget && (
              <div className={`ov-pcard goal ${baseMode === "target" ? "sel" : "off"}`} onClick={() => setBaseMode("target")}>
                <div className="k">목표<span className="tag">{baseMode === "target" ? "ON" : "OFF"}</span></div>
                <div className="v num">{pctSigned(winTarget)}</div>
              </div>
            )}
            {hasBench && (
              <div className={`ov-pcard saa ${baseMode === "bench" ? "sel" : "off"}`} onClick={() => setBaseMode("bench")}>
                <div className="k">{benchLabel}<span className="tag">{baseMode === "bench" ? "ON" : "OFF"}</span></div>
                <div className="v num">{pctSigned(winBench)}</div>
              </div>
            )}
          </div>
        </div>

        <div className="ov-chartwrap">
          <NavChart
            points={sliced}
            benchmarkKind={benchKind}
            benchmarkLabel={benchLabel}
            showBm={baseMode === "bench" && hasBench}
            showTarget={baseIsTarget}
            targetAnnual={target}
            inceptionDate={inception ?? undefined}
            instanceKey={`${fundCode}-${start}-${end}-${sliced.length}`}
          />
        </div>

        {/* 기간별 수익률 표 (성과분석 탭과 동일 양식) — 차트 하단 */}
        <div className="ov-ptbl">
          <div className="t">기간별 수익률</div>
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
                  const v = pr[k];
                  return <td key={k} className={`r num ${v != null ? sign(v) : ""}`}>{v != null ? pctSigned(v) : "—"}</td>;
                })}
              </tr>
              <tr>
                <td>{benchLabel} 수익률</td>
                {PERIOD_COLS.map(([k]) => {
                  const v = bmpr[k];
                  return <td key={k} className={`r num ${v != null ? sign(v) : ""}`}>{v != null ? pctSigned(v) : "—"}</td>;
                })}
              </tr>
              <tr>
                <td>초과</td>
                {PERIOD_COLS.map(([k]) => {
                  const a = pr[k]; const b = bmpr[k];
                  const ex = a != null && b != null ? a - b : null;
                  return <td key={k} className={`r num b ${ex != null ? sign(ex) : ""}`}>{ex != null ? pctSigned(ex) : "—"}</td>;
                })}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
