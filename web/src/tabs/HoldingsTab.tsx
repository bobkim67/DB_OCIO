import { useState } from "react";
import { useHoldings } from "../hooks/useHoldings";
import { useAssetClassReturn, useSecurityReturn } from "../hooks/useTransactions";
import LoadingBar from "../components/common/LoadingBar";
import EquityFocusChart from "../components/charts/EquityFocusChart";
import BondDurationChart from "../components/charts/BondDurationChart";
import SecurityReturnChart from "../components/charts/SecurityReturnChart";
import type { HoldingItemDTO, ComplianceItemDTO } from "../api/endpoints";

interface Props { fundCode: string; }

// 포커스 "종목" 뷰 선택 — 종목 OR 자산군
type HoldSel = { kind: "sec"; cd: string; nm: string } | { kind: "asset"; ac: string };
// 커서 추종 즉시 툴팁 (native title 지연 제거)
type Tip = { x: number; y: number; lines: string[] } | null;

const ASSET_ORDER = ["국내주식", "해외주식", "국내채권", "해외채권", "대체투자", "FX", "모펀드", "유동성"];
const ASSET_COLOR: Record<string, string> = {
  국내주식: "#E8473B", 해외주식: "#557EAA", 국내채권: "#2E9E7B", 해외채권: "#8E7CC3",
  대체투자: "#D9A441", FX: "#19D3F3", 모펀드: "#FF6692", 유동성: "#AAB2BD",
};
const STATUS_LABEL: Record<string, string> = { ok: "적합", warn: "주의", breach: "위반", none: "—" };

const pct1 = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)}%`);
const eok =(v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "—" : `${(v / 1e8).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}억`);
const num = (v: number | null | undefined, d = 1, s = "") => (v == null || !Number.isFinite(v) ? "—" : v.toFixed(d) + s);

export default function HoldingsTab({ fundCode }: Props) {
  const [lookthrough, setLookthrough] = useState(true);
  const [focus, setFocus] = useState<"eq" | "bd" | "sec">("eq");
  const [expandTable, setExpandTable] = useState(false);
  const [sel, setSel] = useState<HoldSel | null>(null);
  const [tip, setTip] = useState<Tip>(null);
  const { data, isLoading, error } = useHoldings(fundCode, lookthrough);

  // 종목/자산군 차트(비중·수익률·거래) — 선택 1년 구간. hooks 규칙상 early return 전 호출.
  const _asof = data?.as_of_date ?? "";
  const secStart = _asof.length >= 10 ? `${Number(_asof.slice(0, 4)) - 1}${_asof.slice(4)}` : "";
  const secRetQ = useSecurityReturn(fundCode, sel?.kind === "sec" ? sel.cd : "", sel?.kind === "sec" ? sel.nm : "", secStart, _asof);
  const assetRetQ = useAssetClassReturn(fundCode, sel?.kind === "asset" ? sel.ac : "", secStart, _asof);

  if (isLoading) return <LoadingBar label="loading holdings..." />;
  if (error || !data) return <div style={{ color: "#dc2626" }}>failed to load holdings</div>;

  const acw = data.asset_class_weights ?? [];
  const items = data.holdings_items ?? [];
  const isEmpty = items.length === 0;
  const ds = data.duration_summary;
  const ef = data.equity_focus;
  const mix = data.portfolio_mix;
  const bonds = items.filter((it) => it.asset_class === "국내채권" || it.asset_class === "해외채권");

  // 만기/신용 틸트 (채권)
  const bondW = bonds.reduce((s, b) => s + b.weight, 0) || 1;
  const matBuckets = { 단기: 0, 중기: 0, 장기: 0 };
  bonds.forEach((b) => {
    if (b.duration == null) return;
    if (b.duration < 3) matBuckets.단기 += b.weight;
    else if (b.duration < 10) matBuckets.중기 += b.weight;
    else matBuckets.장기 += b.weight;
  });
  const krBondW = bonds.filter((b) => b.asset_class === "국내채권").reduce((s, b) => s + b.weight, 0);
  const ovBondW = bonds.filter((b) => b.asset_class === "해외채권").reduce((s, b) => s + b.weight, 0);

  const ord = (ac: string) => { const i = ASSET_ORDER.indexOf(ac); return i < 0 ? 99 : i; };
  const sortedAcw = [...acw].sort((a, b) => ord(a.asset_class) - ord(b.asset_class));
  const maxGroupW = Math.max(...sortedAcw.map((w) => w.weight), 0.0001);

  return (
    <section className="hd-root">
      <div className="hd-head">
        <h2>{data.fund_name} <span className="code">{data.fund_code}</span></h2>
        <div className="nav num">순자산 <b>{eok(data.nast_amt)}</b>{data.as_of_date ? ` · 기준일자 ${data.as_of_date}` : ""}
          {data.data_note ? (
            <span title="환매정산중: 환매가 잡혔으나 증권 미매도로 증권평가>NAST → 비중이 왜곡되어 직전 정상일을 표시합니다."
              style={{ marginLeft: 8, fontSize: 11, fontWeight: 600, padding: "1px 7px", borderRadius: 999,
                color: data.data_pending ? "#9a3412" : "#92400e",
                background: data.data_pending ? "#fee2e2" : "#fef3c7",
                border: `1px solid ${data.data_pending ? "#fecaca" : "#fde68a"}` }}>
              {data.data_pending ? "⚠ " : ""}{data.data_note}
            </span>
          ) : (
            <span style={{ marginLeft: 8, fontSize: 11, color: "#16a34a", fontWeight: 600 }}>✔ 확정</span>
          )}
        </div>
        <label className="hd-lt">
          <input type="checkbox" checked={lookthrough} onChange={(e) => setLookthrough(e.target.checked)} />
          look-through{data.lookthrough_applied ? " (적용)" : ""}
        </label>
      </div>

      {isEmpty ? (
        <div style={{ color: "#6b7280", padding: 16 }}>데이터 없음 (fallback)</div>
      ) : (
        <>
          {/* 스택바 */}
          <div className="hd-card hd-hero hd-mb">
            <div className="hd-stack">
              {sortedAcw.map((w) => (
                <div key={w.asset_class}
                  onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, lines: [`${w.asset_class} ${(w.weight * 100).toFixed(1)}%`, `${eok(w.evl_amt)} · ${w.item_count}종목`] })}
                  onMouseLeave={() => setTip(null)}
                  style={{ width: `${w.weight * 100}%`, background: w.color ?? ASSET_COLOR[w.asset_class] ?? "#AAB2BD" }}>
                  {w.weight >= 0.08 ? `${w.asset_class} ${(w.weight * 100).toFixed(1)}%` : ""}
                </div>
              ))}
            </div>
            <div className="hd-legend">
              {sortedAcw.map((w) => (
                <span key={w.asset_class}><i style={{ background: w.color ?? ASSET_COLOR[w.asset_class] ?? "#AAB2BD" }} />{w.asset_class} {(w.weight * 100).toFixed(1)}%</span>
              ))}
            </div>
          </div>

          {/* 컴플 게이지 */}
          {data.compliance.length > 0 && (
            <div className="hd-mb">
              <div className="hd-gauges">
                {data.compliance.map((c) => <Gauge key={c.key} c={c} setTip={setTip} />)}
              </div>
            </div>
          )}

          <div className="hd-cols">
            {/* 편입종목 테이블 */}
            <div className="hd-card hd-tbl">
              <div style={{ display: "flex", alignItems: "center", margin: "2px 14px 6px" }}>
                <h3 style={{ margin: 0 }}>편입 현황</h3>
                <button type="button" className="hd-expand" onClick={() => setExpandTable((v) => !v)}>
                  {expandTable ? "접기 ▴" : "펼치기 ▾"}
                </button>
              </div>
              <table>
                <colgroup>
                  <col />
                  <col style={{ width: 50 }} />
                  <col style={{ width: 58 }} />
                  <col style={{ width: 50 }} />
                  <col style={{ width: 84 }} />
                  <col style={{ width: 52 }} />
                  <col style={{ width: 56 }} />
                  <col style={{ width: 92 }} />
                </colgroup>
                <thead><tr><th className="l">종목</th><th className="wbl" /><th>비중</th><th className="wbr" /><th>평가액</th><th>Dur</th><th>YTM</th><th>최초 편입일</th></tr></thead>
                <tbody>
                  {sortedAcw.map((g) => {
                    const bucket = items.filter((it) => it.asset_class === g.asset_class);
                    const bucketRows = g.asset_class === "유동성" ? collapseLiquidity(bucket) : bucket;
                    const col = g.color ?? ASSET_COLOR[g.asset_class] ?? "#AAB2BD";
                    const hasBond = g.asset_class === "국내채권" || g.asset_class === "해외채권";
                    const gDur = hasBond ? avgWeighted(bucket, (b) => b.duration) : null;
                    const gYtm = hasBond ? avgWeighted(bucket, (b) => b.ytm) : null;
                    return [
                      <tr className="grp hd-clickrow" key={`g-${g.asset_class}`}
                        onClick={() => { setSel({ kind: "asset", ac: g.asset_class }); setFocus("sec"); }}
                        title={`클릭 → ${g.asset_class} 비중·수익률·거래 차트`}>
                        <td className="l"><span className="dt" style={{ background: col }} /><span className="gn">{g.asset_class}</span></td>
                        <td className="wbl"><span className="hd-wbar gwb"><i style={{ width: `${(g.weight / maxGroupW) * 100}%`, background: col }} /></span></td>
                        <td><span className="gw num">{pct1(g.weight)}</span></td>
                        <td className="wbr" />
                        <td className="num gd">{eok(g.evl_amt)}</td>
                        <td className="num gd">{num(gDur, 1)}</td>
                        <td className="num gd">{gYtm == null ? "—" : num(gYtm, 2)}</td>
                        <td className="num gd" />
                      </tr>,
                      ...(expandTable ? bucketRows.map((it, i) => {
                        const clickable = it.item_cd !== "_CASH_RESIDUAL_" && it.item_cd !== "_LIQ_ETC_";
                        return (
                        <tr key={`${g.asset_class}-${it.item_cd}-${i}`}
                          className={clickable ? "hd-clickrow" : undefined}
                          onClick={clickable ? () => { setSel({ kind: "sec", cd: it.item_cd, nm: it.item_nm }); setFocus("sec"); } : undefined}
                          title={clickable ? "클릭 → 종목 비중·수익률·거래 차트" : undefined}>
                          <td className="l">{it.item_nm}{it.is_short ? <span className="hd-hytag">SHORT</span> : null}</td>
                          <td className="wbl" />
                          <td><b className="num" style={it.weight < 0 ? { color: "#C0392B" } : undefined}>{pct1(it.weight)}</b></td>
                          <td className="wbr"><span className="hd-wbar"><i style={{ width: `${Math.max(0, Math.min((it.weight / Math.max(g.weight, 0.0001)) * 100, 100))}%`, background: it.weight < 0 ? "#C0392B" : col }} /></span></td>
                          <td className="num sub">{eok(it.evl_amt)}</td>
                          <td className="num sub">{num(it.duration, 1)}</td>
                          <td className="num sub">{it.ytm == null ? "—" : num(it.ytm, 2)}</td>
                          <td className="num sub">{it.first_date ?? "—"}</td>
                        </tr>
                        );
                      }) : []),
                    ];
                  })}
                </tbody>
              </table>
            </div>

            {/* 포커스 토글 패널 */}
            <div className="hd-card hd-focus">
              <div className="hd-ftop">
                <span className="ft">{focus === "eq" ? "주식 포커스 — 밸류에이션 × 실적" : focus === "bd" ? "채권 포커스 — 듀레이션 분포" : sel?.kind === "asset" ? `자산군 — ${sel.ac}` : sel?.kind === "sec" ? `종목 — ${sel.nm}` : "종목·자산군 추이"}</span>
                <div className="hd-seg">
                  <button type="button" className={focus === "eq" ? "on" : ""} onClick={() => setFocus("eq")}>주식 포커스</button>
                  <button type="button" className={focus === "bd" ? "on" : ""} onClick={() => setFocus("bd")}>채권 포커스</button>
                  <button type="button" className={focus === "sec" ? "on" : ""} onClick={() => setFocus("sec")}>종목</button>
                </div>
              </div>

              {focus === "eq" && ef && (
                <div>
                  <div className="hd-bsum">
                    <div><div className="k">주식 비중</div><div className="v num">{pct1(ef.equity_weight)}</div></div>
                    <div><div className="k">가중 PER</div><div className="v num">{num(ef.weighted_per, 1, "x")}</div></div>
                    <div><div className="k">가중 EPS성장</div><div className="v num" style={{ color: "#2E7D52" }}>{ef.weighted_eps_growth == null ? "—" : `+${(ef.weighted_eps_growth * 100).toFixed(0)}%`}</div></div>
                  </div>
                  <EquityFocusChart focus={ef} instanceKey={`${fundCode}-eq`} />
                  <div className="hd-fmeta">
                    <div className="hd-tilt"><TiltBar label="지역" parts={[["국내", ef.region_tilt?.["국내"] ?? 0, "#E8473B"], ["해외", ef.region_tilt?.["해외"] ?? 0, "#557EAA"]]} /></div>
                    <div className="hd-tilt"><TiltBar label="스타일" parts={[["성장", ef.style_tilt?.["성장"] ?? 0, "#7C6FE0"], ["가치", ef.style_tilt?.["가치"] ?? 0, "#557EAA"], ["기타", ef.style_tilt?.["기타"] ?? 0, "#AAB2BD"]]} /></div>
                  </div>
                </div>
              )}

              {focus === "bd" && (
                <div>
                  <div className="hd-bsum">
                    <div><div className="k">채권 비중</div><div className="v num">{pct1(mix?.bond_weight)}</div></div>
                    <div><div className="k">가중 듀레이션</div><div className="v num">{num(ds?.duration_bond, 1, "년")}</div></div>
                    <div><div className="k">가중 YTM</div><div className="v num">{ds?.ytm_bond == null ? "—" : num(ds.ytm_bond, 2, "%")}</div></div>
                  </div>
                  <BondDurationChart bonds={bonds} avgDuration={ds?.duration_bond ?? null} instanceKey={`${fundCode}-bd`} />
                  <div className="hd-fmeta">
                    <div className="hd-tilt"><TiltBar label="만기" parts={[["단기", matBuckets.단기 / bondW, "#9FD3BE"], ["중기", matBuckets.중기 / bondW, "#2E9E7B"], ["장기", matBuckets.장기 / bondW, "#1F6F54"]]} /></div>
                    <div className="hd-tilt"><TiltBar label="신용" parts={[["국채/IG", krBondW / bondW, "#2E9E7B"], ["HY", ovBondW / bondW, "#8E7CC3"]]} /></div>
                  </div>
                </div>
              )}

              {focus === "sec" && (!sel ? (
                <div style={{ padding: "48px 16px", color: "var(--ace-ink-3)", textAlign: "center", fontSize: 13 }}>
                  좌측 표에서 <b>자산군</b> 또는 <b>종목</b>을 클릭하면 비중·수익률·거래내역이 표시됩니다.
                </div>
              ) : sel.kind === "asset" ? (
                <div>
                  <div className="hd-bsum">
                    <div><div className="k">자산군</div><div className="v" style={{ fontSize: 14 }}>{sel.ac}</div></div>
                    <div><div className="k">비중</div><div className="v num">{pct1(acw.find((w) => w.asset_class === sel.ac)?.weight)}</div></div>
                    <div><div className="k">평가액</div><div className="v num">{eok(acw.find((w) => w.asset_class === sel.ac)?.evl_amt)}</div></div>
                  </div>
                  {assetRetQ.isLoading ? (
                    <div style={{ padding: 40, color: "var(--ace-ink-3)", textAlign: "center" }}>로딩 중…</div>
                  ) : (
                    <SecurityReturnChart
                      points={assetRetQ.data?.points ?? []}
                      trades={assetRetQ.data?.trades ?? []}
                      weights={assetRetQ.data?.weights ?? []}
                      weightComponents={assetRetQ.data?.weight_components ?? []}
                      tradeComponents={assetRetQ.data?.trade_components ?? []}
                      itemNm={sel.ac}
                      instanceKey={`${fundCode}-asset-${sel.ac}`}
                      xRange={[secStart, _asof]}
                    />
                  )}
                </div>
              ) : (
                <div>
                  <div className="hd-bsum">
                    <div><div className="k">종목</div><div className="v" style={{ fontSize: 13 }}>{sel.nm}</div></div>
                    <div><div className="k">비중</div><div className="v num">{pct1(items.find((it) => it.item_cd === sel.cd)?.weight)}</div></div>
                    <div><div className="k">자산군</div><div className="v" style={{ fontSize: 13 }}>{items.find((it) => it.item_cd === sel.cd)?.asset_class ?? "—"}</div></div>
                  </div>
                  {secRetQ.isLoading ? (
                    <div style={{ padding: 40, color: "var(--ace-ink-3)", textAlign: "center" }}>로딩 중…</div>
                  ) : (
                    <SecurityReturnChart
                      points={secRetQ.data?.points ?? []}
                      trades={secRetQ.data?.trades ?? []}
                      weights={secRetQ.data?.weights ?? []}
                      itemNm={sel.nm}
                      instanceKey={`${fundCode}-sec-${sel.cd}`}
                      xRange={[secStart, _asof]}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}
      {tip && (
        <div className="hd-tip2" style={{ left: tip.x + 14, top: tip.y + 14 }}>
          {tip.lines.map((l, i) => <div key={i} className={i === 0 ? "h" : undefined}>{l}</div>)}
        </div>
      )}
    </section>
  );
}

// 유동성 = 예금·USD Deposit·현금/미수금만 개별 노출, 나머지(콜론·MMF·REPO 등)는 "기타"로 합산
function collapseLiquidity(items: HoldingItemDTO[]): HoldingItemDTO[] {
  const keep: HoldingItemDTO[] = [];
  let etcW = 0, etcE = 0, etcBase: HoldingItemDTO | null = null;
  for (const it of items) {
    const nm = it.item_nm.toUpperCase();
    const show = it.item_cd === "_CASH_RESIDUAL_"
      || it.item_cd === "_REDEMPTION_PAYABLE_"
      || it.item_cd.toUpperCase() === "USMUSD022001"
      || nm.includes("DEPOSIT")
      || it.item_nm.includes("예금");
    if (show) keep.push(it);
    else { etcW += it.weight; etcE += it.evl_amt; etcBase = it; }
  }
  if (etcBase) keep.push({ ...etcBase, item_cd: "_LIQ_ETC_", item_nm: "기타", weight: etcW, evl_amt: etcE, duration: null, ytm: null, is_short: false, first_date: null });
  return keep;
}

function avgWeighted(items: HoldingItemDTO[], pick: (it: HoldingItemDTO) => number | null | undefined): number | null {
  let num = 0, den = 0;
  for (const it of items) {
    const v = pick(it);
    if (v == null || !Number.isFinite(v)) continue;
    num += v * it.weight; den += it.weight;
  }
  return den > 0 ? num / den : null;
}

// 컴플 게이지 (시안 A) — 라벨+상태 / 큰 값 / 여유·초과 색상 서브라인 / 트랙(허용·위반 음영+기준선+초과분) / 기준선 마커 레전드
function Gauge({ c, setTip }: { c: ComplianceItemDTO; setTip: (t: Tip) => void }) {
  const lo = c.band_low, hi = c.band_high;
  const isRef = c.status === "none" && hi != null; // SAA 비교용
  const V = c.value;
  const kind: "band" | "ref" | "max" | "min" | "none" =
    lo != null && hi != null ? "band" : hi != null ? (isRef ? "ref" : "max") : lo != null ? "min" : "none";
  const T = kind === "min" ? lo! : hi ?? null; // 기준선 위치
  const axisRef = kind === "band" ? hi! : T ?? V;
  const axisMax = Math.max(V, axisRef ?? V, 0.0001) * 1.18;
  const P = (x: number) => Math.min(100, Math.max(0, (x / axisMax) * 100));
  const pp = (x: number) => `${P(x)}%`;
  const pc0 = (x: number) => `${(x * 100).toFixed(0)}%`;

  const stColor =
    c.status === "breach" ? "#C0392B" : c.status === "warn" ? "#C8862B" : c.status === "ok" ? "#2E9E7B" : "#557EAA";
  const over = kind === "max" && hi != null && V > hi ? V - hi : 0;
  const short = kind === "min" && lo != null && V < lo ? lo - V : 0;

  // 기준선 마커 레전드 (툴팁용, 가이드 임계값 포함)
  const markerLeg =
    kind === "ref" ? `SAA 목표 ${pc0(hi!)}`
    : kind === "max" ? `가이드 기준선(≤${pc0(hi!)})`
    : kind === "min" ? `가이드 기준선(≥${pc0(lo!)})`
    : kind === "band" ? `가이드 기준선(${pc0(lo!)}~${pc0(hi!)})`
    : "가이드 미설정";
  // 기준선 바로 위 라벨 (≤x% 등)
  const mkLabel =
    kind === "max" ? `≤${pc0(hi!)}`
    : kind === "min" ? `≥${pc0(lo!)}`
    : kind === "band" ? `${pc0(lo!)}~${pc0(hi!)}`
    : kind === "ref" ? `SAA ${pc0(hi!)}`
    : "";
  const mkLeft = T != null ? Math.min(92, Math.max(8, P(T))) : 0;

  let note = "", noteCls = "ok";
  if (over > 0) { note = `초과 +${(over * 100).toFixed(1)}%p`; noteCls = "bad"; }
  else if (short > 0) { note = `미달 −${(short * 100).toFixed(1)}%p`; noteCls = "bad"; }
  else if (isRef) { const d = V - hi!; note = `현재 ${d >= 0 ? "+" : "−"}${(Math.abs(d) * 100).toFixed(1)}%p vs SAA`; noteCls = "ref"; }
  else if (kind === "max") { note = `여유 +${((hi! - V) * 100).toFixed(1)}%p`; noteCls = "ok"; }
  else if (kind === "min") { note = `여유 +${((V - lo!) * 100).toFixed(1)}%p`; noteCls = "ok"; }

  const tipLines = [c.label, `현재 ${pct1(V)} · ${markerLeg}`, `${isRef ? "비교" : STATUS_LABEL[c.status]}${note ? ` · ${note}` : ""}`];

  return (
    <div className="hd-card hd-g2"
      onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, lines: tipLines })}
      onMouseLeave={() => setTip(null)}>
      <div className="t">
        <span className="lbl">{c.label}{c.breakdown ? <span className="bd">({c.breakdown})</span> : null}</span>
        <span className={`st ${c.status}`}>{isRef ? "비교" : STATUS_LABEL[c.status]}</span>
      </div>
      <div className="vrow">
        <span className="v num">{pct1(V)}</span>
        {note && <span className={`vn ${noteCls}`}>{note}</span>}
      </div>
      {T != null && mkLabel && (
        <div className="mkrow"><span className="mklab" style={{ left: `${mkLeft}%` }}>{mkLabel}</span></div>
      )}
      <div className="track2">
        {kind === "max" && (<><div className="zone ok" style={{ left: 0, width: pp(hi!) }} /><div className="zone bad" style={{ left: pp(hi!), right: 0 }} /></>)}
        {kind === "min" && (<><div className="zone bad" style={{ left: 0, width: pp(lo!) }} /><div className="zone ok" style={{ left: pp(lo!), right: 0 }} /></>)}
        {kind === "band" && (<><div className="zone bad" style={{ left: 0, width: pp(lo!) }} /><div className="zone ok" style={{ left: pp(lo!), width: `${P(hi!) - P(lo!)}%` }} /><div className="zone bad" style={{ left: pp(hi!), right: 0 }} /></>)}
        {kind === "ref" && <div className="zone neu" style={{ left: 0, right: 0 }} />}
        {/* 값 막대: 초과 시 허용분(녹)+초과분(빨강) 분리 */}
        <div className="fill2" style={{ width: pp(over > 0 ? hi! : V), background: over > 0 ? "#2E9E7B" : stColor }} />
        {over > 0 && <div className="fill2 over" style={{ left: pp(hi!), width: `${P(V) - P(hi!)}%` }} />}
        {short > 0 && <div className="gap2" style={{ left: pp(V), width: `${P(lo!) - P(V)}%` }} />}
        {/* 가이드 기준선 */}
        {T != null && <div className="mk" style={{ left: pp(T) }} />}
      </div>
      {kind !== "ref" && kind !== "none" && (
        <div className="mleg">
          <span className="li"><span className="zsw zok" />허용 구간</span>
          <span className="li"><span className="zsw zbad" />위반·초과 구간</span>
        </div>
      )}
    </div>
  );
}

function TiltBar({ label, parts }: { label: string; parts: [string, number, string][] }) {
  const tot = parts.reduce((s, p) => s + p[1], 0) || 1;
  const pctOf = (v: number) => (v / tot * 100).toFixed(0);
  const tip = `${label} — ` + parts.filter((p) => p[1] > 0).map((p) => `${p[0]} ${pctOf(p[1])}%`).join(" · ");
  return (
    <>
      <div className="lab"><span>{label}</span></div>
      <div className="bar" title={tip}>{parts.map((p) => <i key={p[0]} style={{ width: `${p[1] / tot * 100}%`, background: p[2] }} />)}</div>
      <div className="tleg">
        {parts.filter((p) => p[1] > 0).map((p) => (
          <span key={p[0]}><i style={{ background: p[2] }} />{p[0]} {pctOf(p[1])}%</span>
        ))}
      </div>
    </>
  );
}
