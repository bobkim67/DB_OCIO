import { useEffect, useState } from "react";
import { useHoldings } from "../hooks/useHoldings";
import { useFunds } from "../hooks/useFunds";
import { useAssetClassReturn, useSecurityReturn } from "../hooks/useTransactions";
import LoadingBar from "../components/common/LoadingBar";
import EquityFocusChart from "../components/charts/EquityFocusChart";
import BondDurationChart from "../components/charts/BondDurationChart";
import SecurityReturnChart from "../components/charts/SecurityReturnChart";
import type { HoldingItemDTO, ComplianceItemDTO } from "../api/endpoints";
import { unreflectedSummary } from "../lib/pendingSettlement";
import { secAlias } from "../lib/securityAlias";

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
// 로컬 타임존 기준 오늘 YYYY-MM-DD (기준일 date input max용)
const todayStr = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export default function HoldingsTab({ fundCode }: Props) {
  const [lookthrough, setLookthrough] = useState(true);
  const [focus, setFocus] = useState<"eq" | "bd" | "sec">("eq");
  const [expandTable, setExpandTable] = useState(true);   // 편입현황 기본 펼침 (2026-07-30 사용자 지시)
  const [sel, setSel] = useState<HoldSel | null>(null);
  const [tip, setTip] = useState<Tip>(null);
  // 기준일자 스냅샷 — "" = 최신. 지정 시 해당일(이전 최근 영업일) 보유 스냅샷 조회.
  // draftAsOf = 입력값(조회 전), asOf = 적용값 — 조회 버튼으로만 갱신 (2026-07-08)
  const [asOf, setAsOf] = useState<string>("");
  const [draftAsOf, setDraftAsOf] = useState<string>("");
  const { data, isLoading, error } = useHoldings(fundCode, lookthrough, asOf || undefined);
  const { data: fundsData } = useFunds();   // 편입현황 합계행 설정일용

  // 펀드 변경 시 기준일 리셋, 입력 비어 있으면 최신 데이터일로 디폴트 세팅
  useEffect(() => { setAsOf(""); setDraftAsOf(""); }, [fundCode]);
  useEffect(() => {
    if (data?.as_of_date && !draftAsOf) setDraftAsOf(data.as_of_date);
  }, [data?.as_of_date, draftAsOf]);

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
  // 결제 예정 — source='mail' 은 원장 미반영(비중에 없음), 'ledger' 는 미지급금으로 반영됨
  const pending = data.pending_settlements ?? [];
  const unreflected = unreflectedSummary(pending);   // 원장 미반영(해외)만 — 상단 카드용
  const hasMailPending = unreflected !== null;
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

  // 편입현황 합계행 — 평가액=Σ자산군, Dur/YTM=펀드 전체(채권비중×채권Dur/YTM =
  // duration_summary overall, Admin 패널과 동일 정의), 최초편입일=펀드 설정일
  const totalEvl = sortedAcw.reduce((s, w) => s + w.evl_amt, 0);
  const fundInception = fundsData?.data.find((f) => f.code === fundCode)?.inception ?? null;

  // FX 포지션 — 합계 아래 한 행. NAV 구성이 아니라 holdings_items 에서 빠져 있다.
  const fxPos = data.fx_positions ?? [];

  // 07G04 예외(사용자 지정 2026-07-02): look-through 해제 시 상단 스택바의 모펀드
  // 버킷을 수익추구/인컴추구 모펀드별 세그먼트로 분해해 혼합 비율을 표기.
  const motherShort = (nm: string) =>
    nm.includes("수익추구") ? "수익추구" : nm.includes("인컴추구") ? "인컴추구" : nm;
  const MOTHER_SEG_COLORS: Record<string, string> = { 수익추구: "#FF6692", 인컴추구: "#C9578C" };
  type StackSeg = { key: string; label: string; weight: number; evl_amt: number; color: string; note: string };
  const stackSegs: StackSeg[] = sortedAcw.flatMap((w) => {
    const base: StackSeg = {
      key: w.asset_class, label: w.asset_class, weight: w.weight, evl_amt: w.evl_amt,
      color: w.color ?? ASSET_COLOR[w.asset_class] ?? "#AAB2BD",
      note: `${w.item_count}종목`,
    };
    if (fundCode !== "07G04" || w.asset_class !== "모펀드") return [base];
    const mothers = items.filter((it) => it.asset_class === "모펀드");
    if (mothers.length === 0) return [base];
    return mothers
      .slice()
      .sort((a, b) => b.weight - a.weight)
      .map((it) => {
        const lb = motherShort(it.item_nm);
        return {
          key: `모펀드-${it.item_cd}`, label: lb, weight: it.weight, evl_amt: it.evl_amt,
          color: MOTHER_SEG_COLORS[lb] ?? ASSET_COLOR.모펀드, note: "모펀드",
        };
      });
  });

  // 기준일 dirty — 입력값이 적용값(미지정 시 최신 데이터일)과 다르면 조회 필요
  const effectiveAsOf = asOf || data.as_of_date || "";
  const asOfDirty = draftAsOf !== "" && draftAsOf !== effectiveAsOf;
  // 모자(FoF) 구조 여부 — look-through 적용 중이거나(전개돼 모펀드 행 없음) 보유에 모펀드 존재
  const isFoF = data.lookthrough_applied || items.some((it) => it.asset_class === "모펀드");

  return (
    <section className="hd-root">
      <div className="hd-head">
        <h2 className="fund-title">
          {data.fund_name} <span className="code">{data.fund_code}</span>
          {/* 원장 미반영(해외 체결확인서) 카드 — 펀드코드 우측 (2026-08-03 사용자 지시).
              미지급금(원장 반영분)은 카드에서 제외 — 아래 '결제 예정' 배너에만 표기. */}
          {unreflected && (
            <span className="hd-unreflected" title={unreflected.detail}>
              ⚠ {unreflected.label}
            </span>
          )}
        </h2>
      </div>

      {/* 컨트롤 패널 — look-through 토글 + 기준일(조회 버튼 갱신) + 해당일 NAV 카드 (2026-07-08) */}
      <div className="hd-card hd-mb">
        <div className="tx-ctrl">
          <span className="lab">기준일</span>
          <span className="tx-date" title="기준일자 지정 — 주말·공휴일 선택 시 직전 영업일 스냅샷.">
            <input type="date" value={draftAsOf} max={todayStr()}
              onChange={(e) => setDraftAsOf(e.target.value)} />
          </span>
          <button type="button" className="bn-apply" onClick={() => setAsOf(draftAsOf)} disabled={!asOfDirty}>
            조회
          </button>
          {asOf && (
            <button type="button" className="hd-expand" onClick={() => { setAsOf(""); setDraftAsOf(""); }}>
              최신
            </button>
          )}
          {asOfDirty && <span className="bn-dirty">변경됨 — 조회를 눌러 갱신</span>}
          {/* look-through 토글 — 모자(FoF) 구조 펀드에서만 노출 (2026-07-08) */}
          {isFoF && (
            <>
              <span className="div" />
              <span className="lab">look-through</span>
              <div className="tx-seg">
                <button type="button" className={lookthrough ? "on" : ""} onClick={() => setLookthrough(true)}>On</button>
                <button type="button" className={!lookthrough ? "on" : ""} onClick={() => setLookthrough(false)}>Off</button>
              </div>
            </>
          )}
          {/* 환매정산중 경고 배지 — data_pending(증권평가>순자산으로 비중이 실제 왜곡된 상태)일
              때만 남긴다. 단순 '결제 대기 — 매입미지급금 반영'은 비중이 정상 균형이라
              배지를 걷어내고 아래 '결제 예정' 배너 목록으로 일원화 (2026-08-03 사용자 지시). */}
          {data.data_pending && data.data_note && (
            <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 600, padding: "1px 7px", borderRadius: 999,
                color: "#9a3412", background: "#fee2e2", border: "1px solid #fecaca" }}
              title="환매정산중: 환매대금이 미지급금(부채)으로 먼저 차감돼 증권평가>순자산인 상태. 당일 스냅샷 그대로 표시하되 음수 '환매미지급금' 유동성 라인으로 합계 100%를 맞춥니다. 결제일에 증권 매도로 청산되면 해소됩니다.">
              ⚠ {data.data_note}
            </span>
          )}
        </div>
      </div>

      {/* 결제 예정 안내 (2026-08-03) — 비중은 원장 그대로, 안내만. 상세는 아래 주석 참조 */}
      {pending.length > 0 && (
        <div className="hd-card hd-mb" style={{ borderLeft: "3px solid #d9a441" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: "#8a6d1f" }}>
              ⓘ 결제 예정 {pending.length}건
            </span>
            <span style={{ fontSize: 11, color: "#6b7280" }}>
              기준일({data.as_of_date}) 시점에 결제 미도래 — 아래 비중에는 {hasMailPending ? "일부 미반영" : "미지급금으로 반영됨"}
            </span>
          </div>
          <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: "#374151", lineHeight: 1.75 }}>
            {pending.map((p, i) => (
              <li key={i}>
                <span style={{ fontWeight: 600 }}>{secAlias(p.item_nm)}</span>
                {p.ticker ? <span style={{ color: "#9ca3af" }}> ({p.ticker})</span> : null}
                {" "}{p.side}
                {p.qty ? ` ${p.qty.toLocaleString("ko-KR")}주` : ""}
                {" · "}
                {p.ccy !== "KRW" && p.amount != null
                  ? `${p.ccy} ${p.amount.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${p.amount_krw ? ` (약 ${eok(p.amount_krw)})` : ""}`
                  : eok(p.amount_krw ?? p.amount)}
                <span style={{ color: "#6b7280" }}>
                  {" · "}체결 {p.trade_date ?? "—"} · 결제 {p.settle_date ?? "—"}
                  {p.reflect_date ? ` · ${p.reflect_date} 반영` : ""}
                </span>
                <span style={{
                  marginLeft: 8, fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 999,
                  color: p.source === "mail" ? "#9a3412" : "#4b5563",
                  background: p.source === "mail" ? "#ffedd5" : "#f3f4f6",
                  border: `1px solid ${p.source === "mail" ? "#fed7aa" : "#e5e7eb"}`,
                }}
                  title={p.source === "mail"
                    ? "브로커 체결확인서(해외거래 메일)에만 있고 원장에는 아직 없음. 해외 거래는 체결 다음 영업일(결제일)에 원장에 잡히므로 그때까지 비중·평가금액에 반영되지 않습니다."
                    : "원장에 이미 반영된 거래로, 결제일만 아직 도래하지 않았습니다. 매입/환매 미지급금(부채)으로 계상돼 유동성이 일시적으로 낮거나 음수로 보일 수 있습니다."}>
                  {p.source === "mail" ? "원장 미반영" : "미지급금 반영"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {isEmpty ? (
        <div style={{ color: "#6b7280", padding: 16 }}>데이터 없음 (fallback)</div>
      ) : (
        <>
          {/* 스택바 */}
          <div className="hd-card hd-hero hd-mb">
            <div className="hd-stack">
              {stackSegs.map((s) => (
                <div key={s.key}
                  onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, lines: [`${s.label} ${(s.weight * 100).toFixed(1)}%`, `${eok(s.evl_amt)} · ${s.note}`] })}
                  onMouseLeave={() => setTip(null)}
                  style={{ width: `${s.weight * 100}%`, background: s.color }}>
                  {s.weight >= 0.08 ? `${s.label} ${(s.weight * 100).toFixed(1)}%` : ""}
                </div>
              ))}
            </div>
            <div className="hd-legend">
              {stackSegs.map((s) => (
                <span key={s.key}><i style={{ background: s.color }} />{s.label} {(s.weight * 100).toFixed(1)}%</span>
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
                  {/* 합계행 — 펀드 전체 (2026-07-24 사용자 지정) */}
                  <tr className="grp" key="total-fund" style={{ borderTop: "2px solid var(--ace-line-2)" }}>
                    <td className="l"><span className="gn">펀드</span></td>
                    <td className="wbl" />
                    <td><span className="gw num">{pct1(1)}</span></td>
                    <td className="wbr" />
                    <td className="num gd">{eok(totalEvl)}</td>
                    <td className="num gd">{num(ds?.duration_overall, 1)}</td>
                    <td className="num gd">{ds?.ytm_overall == null ? "—" : num(ds.ytm_overall, 2)}</td>
                    <td className="num gd" style={{ whiteSpace: "nowrap" }}>{fundInception ?? "—"}</td>
                  </tr>
                  {/* FX 포지션 — 합계 **아래** 한 행 (2026-08-07 사용자 지시).
                      NAV 구성이 아니라 포지션(notional)이라 위 100% 에는 안 들어간다.
                      라벨·비중·평가액·최초편입일을 같은 행에 둔다. */}
                  {fxPos.map((p) => (
                    <tr key={`fx-${p.item_cd}`}>
                      <td className="l">
                        <span className="gn">FX 포지션 - {p.item_nm}({p.is_short ? "매도" : "매수"})</span>
                      </td>
                      <td className="wbl" />
                      <td>
                        <span className="gw num">{p.is_short ? "−" : "+"}{pct1(p.weight)}</span>
                      </td>
                      <td className="wbr" />
                      <td className="num gd">{eok(p.evl_amt)}</td>
                      <td className="num gd">—</td>
                      <td className="num gd">—</td>
                      <td className="num gd" style={{ whiteSpace: "nowrap" }}>{p.first_date ?? "—"}</td>
                    </tr>
                  ))}
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
                    <div className="hd-tilt"><TiltBar label="스타일" parts={[["성장", ef.style_tilt?.["성장"] ?? 0, "#7C6FE0"], ["가치", ef.style_tilt?.["가치"] ?? 0, "#557EAA"], ["혼합", ef.style_tilt?.["혼합"] ?? 0, "#AAB2BD"]]} /></div>
                  </div>
                </div>
              )}

              {focus === "bd" && (
                <div>
                  <div className="hd-bsum">
                    <div><div className="k">채권 비중</div><div className="v num">{pct1(mix?.bond_weight)}</div></div>
                    <div><div className="k">가중 듀레이션</div><div className="v num">{num(ds?.duration_bond, 1, "년")}{ds?.duration_overall != null && <span style={{ color: "#98a0ab", fontSize: 12, marginLeft: 3 }} title="괄호=펀드 전체 기준">({num(ds.duration_overall, 1)})</span>}</div></div>
                    <div><div className="k">가중 YTM</div><div className="v num">{ds?.ytm_bond == null ? "—" : num(ds.ytm_bond, 2, "%")}{ds?.ytm_overall != null && <span style={{ color: "#98a0ab", fontSize: 12, marginLeft: 3 }} title="괄호=펀드 전체 기준">({num(ds.ytm_overall, 2)})</span>}</div></div>
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
  // band 는 0 시작이 아니라 가이드 레인지 중심 축 (2026-07-07 사용자 지정):
  // 허용구간(lo~hi)이 트랙 중앙을 차지하고 양옆이 위반 구간(옅은 빨강)으로 보이도록.
  const span = kind === "band" ? hi! - lo! : 0;
  const bandLo = kind === "band" ? Math.max(0, Math.min(lo! - span * 0.6, V - span * 0.2)) : 0;
  const bandHi = kind === "band" ? Math.max(hi! + span * 0.6, V + span * 0.2) : axisMax;
  const P = (x: number) =>
    kind === "band"
      ? Math.min(100, Math.max(0, ((x - bandLo) / Math.max(bandHi - bandLo, 1e-9)) * 100))
      : Math.min(100, Math.max(0, (x / axisMax) * 100));
  const pp = (x: number) => `${P(x)}%`;
  const pc0 = (x: number) => `${(x * 100).toFixed(0)}%`;

  const stColor =
    c.status === "breach" ? "#C0392B" : c.status === "warn" ? "#C8862B" : c.status === "ok" ? "#2E9E7B" : "#557EAA";
  const over = (kind === "max" || kind === "band") && hi != null && V > hi ? V - hi : 0;
  const short = (kind === "min" || kind === "band") && lo != null && V < lo ? lo - V : 0;

  // 기준선 바로 위 라벨 (≤x% 등)
  const mkLabel =
    kind === "max" ? `≤${pc0(hi!)}`
    : kind === "min" ? `≥${pc0(lo!)}`
    : kind === "band" ? ""  /* band 라벨은 하한·상한 개별 표시 (아래 mkrow 분기) */
    : kind === "ref" ? `SAA ${pc0(hi!)}`
    : "";
  const mkLeft = T != null ? Math.min(92, Math.max(8, P(T))) : 0;
  const clampPct = (x: number) => Math.min(92, Math.max(8, P(x)));

  let note = "", noteCls = "ok";
  if (over > 0) { note = `초과 +${(over * 100).toFixed(1)}%p`; noteCls = "bad"; }
  else if (short > 0) { note = `미달 −${(short * 100).toFixed(1)}%p`; noteCls = "bad"; }
  else if (kind === "band") { note = `여유 ±${(Math.min(hi! - V, V - lo!) * 100).toFixed(1)}%p`; noteCls = "ok"; }
  else if (isRef) { const d = V - hi!; note = `현재 ${d >= 0 ? "+" : "−"}${(Math.abs(d) * 100).toFixed(1)}%p vs SAA`; noteCls = "ref"; }
  else if (kind === "max") { note = `여유 +${((hi! - V) * 100).toFixed(1)}%p`; noteCls = "ok"; }
  else if (kind === "min") { note = `여유 +${((V - lo!) * 100).toFixed(1)}%p`; noteCls = "ok"; }

  // 툴팁: `{자산군}({상태})` + `현재 x% · 가이드(중심 ±허용%p)` — 여유 표기는 제거,
  // 위반/미달·SAA 비교만 정보성으로 덧붙임 (2026-07-07 사용자 지정)
  const statusTxt = isRef ? "비교" : STATUS_LABEL[c.status];
  const guideTxt =
    kind === "band" ? `가이드(${pc0((lo! + hi!) / 2)} ±${(((hi! - lo!) / 2) * 100).toFixed(0)}%p)`
    : kind === "max" ? `가이드(≤${pc0(hi!)})`
    : kind === "min" ? `가이드(≥${pc0(lo!)})`
    : kind === "ref" ? `SAA 목표 ${pc0(hi!)}`
    : "가이드 미설정";
  const tipNote = (noteCls === "bad" || noteCls === "ref") && note ? ` · ${note}` : "";
  const tipLines = [`${c.label}(${statusTxt})`, `현재 ${pct1(V)} · ${guideTxt}${tipNote}`];

  return (
    <div className="hd-card hd-g2"
      onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, lines: tipLines })}
      onMouseLeave={() => setTip(null)}>
      {/* 타이틀 행 — 라벨 + 상태칩 + 값(우측) 한 줄 (Overview 지표카드 양식) */}
      <div className="t">
        <span className="lbl">{c.label}{c.breakdown ? <span className="bd">({c.breakdown})</span> : null}</span>
        <span className={`st ${c.status}`}>{statusTxt}</span>
        <span className="v num">{pct1(V)}</span>
      </div>
      <div className="track2">
        {kind === "max" && (<><div className="zone ok" style={{ left: 0, width: pp(hi!) }} /><div className="zone bad" style={{ left: pp(hi!), right: 0 }} /></>)}
        {kind === "min" && (<><div className="zone bad" style={{ left: 0, width: pp(lo!) }} /><div className="zone ok" style={{ left: pp(lo!), right: 0 }} /></>)}
        {kind === "band" && (<><div className="zone bad" style={{ left: 0, width: pp(lo!) }} /><div className="zone ok" style={{ left: pp(lo!), width: `${P(hi!) - P(lo!)}%` }} /><div className="zone bad" style={{ left: pp(hi!), right: 0 }} /></>)}
        {/* ref(SAA 비교) — 판정을 안 하므로(status="none", 핀=파랑) 초록/빨강 존을 쓰지 않는다.
            중립 음영 1색 + SAA 위치 눈금만 (2026-08-26 사용자 지시, 구 07-09 초록/빨강 대체) */}
        {kind === "ref" && (<><div className="zone ref" style={{ left: 0, right: 0 }} /><div className="rmk" style={{ left: pp(hi!) }} /></>)}
        {/* 현재 비중 = 상태색 세로 핀 (전 종류 공통, 2026-07-07 통일).
            가이드 기준선(검정)은 제거 — 존 색 경계 + 경계 위 라벨로 표시 */}
        <div className="vmk" style={{ left: pp(V), background: stColor }} />
      </div>
      {kind === "band" ? (
        /* 레인지 라벨 — 하한·상한 경계 바로 아래에 각각 표시 (2026-07-10 하단 이동) */
        <div className="mkrow">
          <span className="mklab" style={{ left: `${clampPct(lo!)}%` }}>{pc0(lo!)}</span>
          <span className="mklab" style={{ left: `${clampPct(hi!)}%` }}>{pc0(hi!)}</span>
        </div>
      ) : (
        T != null && mkLabel && (
          <div className="mkrow"><span className="mklab" style={{ left: `${mkLeft}%` }}>{mkLabel}</span></div>
        )
      )}
      {kind === "ref" ? (
        /* SAA 는 판정이 아닌 참고선 — 허용/초과 레전드 대신 기준선 표기만 (2026-08-26) */
        <div className="mleg">
          <span className="li"><span className="zsw zref" />SAA 목표 기준선</span>
        </div>
      ) : kind !== "none" && (
        <div className="mleg">
          <span className="li"><span className="zsw zok" />허용 구간</span>
          <span className="li"><span className="zsw zbad" />초과 구간</span>
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
