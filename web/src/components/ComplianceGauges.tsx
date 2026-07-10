// 컴플라이언스 게이지 카드 (공용) — 편입종목 탭과 Admin 컴플 가이드에서 공유.
// 편입종목(PDF) 탭의 "펀드별 상단 컴플위반여부 카드"를 그대로 이식하기 위해
// HoldingsTab 의 Gauge 를 이 파일로 추출했다. 스타일은 holdings.css 사용.
import { useState } from "react";
import type { ComplianceItemDTO } from "../api/endpoints";
import "../styles/holdings.css";

export type Tip = { x: number; y: number; lines: string[] } | null;

const STATUS_LABEL: Record<string, string> = { ok: "적합", warn: "주의", breach: "위반", none: "—" };
const pct1 = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? "—" : `${(v * 100).toFixed(1)}%`;

// 컴플 게이지 — 라벨+상태 / 큰 값 / 여유·초과 서브라인 / 트랙(허용·위반 음영+기준선) / 기준선 마커 레전드
export function ComplianceGauge({ c, setTip }: { c: ComplianceItemDTO; setTip: (t: Tip) => void }) {
  const lo = c.band_low, hi = c.band_high;
  const isRef = c.status === "none" && hi != null; // SAA 비교용
  const V = c.value;
  const kind: "band" | "ref" | "max" | "min" | "none" =
    lo != null && hi != null ? "band" : hi != null ? (isRef ? "ref" : "max") : lo != null ? "min" : "none";
  const T = kind === "min" ? lo! : hi ?? null; // 기준선 위치
  const axisRef = kind === "band" ? hi! : T ?? V;
  const axisMax = Math.max(V, axisRef ?? V, 0.0001) * 1.18;
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

  const mkLabel =
    kind === "max" ? `≤${pc0(hi!)}`
    : kind === "min" ? `≥${pc0(lo!)}`
    : kind === "band" ? ""
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
      <div className="t">
        <span className="lbl">{c.label}{c.breakdown ? <span className="bd">({c.breakdown})</span> : null}</span>
        <span className={`st ${c.status}`}>{statusTxt}</span>
        <span className="v num">{pct1(V)}</span>
      </div>
      {kind === "band" ? (
        <div className="mkrow">
          <span className="mklab" style={{ left: `${clampPct(lo!)}%` }}>{pc0(lo!)}</span>
          <span className="mklab" style={{ left: `${clampPct(hi!)}%` }}>{pc0(hi!)}</span>
        </div>
      ) : (
        T != null && mkLabel && (
          <div className="mkrow"><span className="mklab" style={{ left: `${mkLeft}%` }}>{mkLabel}</span></div>
        )
      )}
      <div className="track2">
        {kind === "max" && (<><div className="zone ok" style={{ left: 0, width: pp(hi!) }} /><div className="zone bad" style={{ left: pp(hi!), right: 0 }} /></>)}
        {kind === "min" && (<><div className="zone bad" style={{ left: 0, width: pp(lo!) }} /><div className="zone ok" style={{ left: pp(lo!), right: 0 }} /></>)}
        {kind === "band" && (<><div className="zone bad" style={{ left: 0, width: pp(lo!) }} /><div className="zone ok" style={{ left: pp(lo!), width: `${P(hi!) - P(lo!)}%` }} /><div className="zone bad" style={{ left: pp(hi!), right: 0 }} /></>)}
        {kind === "ref" && (<><div className="zone ok" style={{ left: 0, width: pp(hi!) }} /><div className="zone bad" style={{ left: pp(hi!), right: 0 }} /></>)}
        <div className="vmk" style={{ left: pp(V), background: stColor }} />
      </div>
      {kind !== "none" && (
        <div className="mleg">
          <span className="li"><span className="zsw zok" />{kind === "ref" ? "SAA 이하" : "허용 구간"}</span>
          <span className="li"><span className="zsw zbad" />{kind === "ref" ? "SAA 초과" : "초과 구간"}</span>
        </div>
      )}
    </div>
  );
}

// 게이지 목록 + 자체 툴팁 호스트 래퍼. 부모의 툴팁 상태 없이 독립 사용 가능(Admin 등).
export default function ComplianceGauges({ items }: { items: ComplianceItemDTO[] }) {
  const [tip, setTip] = useState<Tip>(null);
  if (!items || items.length === 0) return null;
  return (
    <>
      <div className="hd-gauges">
        {items.map((c) => <ComplianceGauge key={c.key} c={c} setTip={setTip} />)}
      </div>
      {tip && (
        <div className="hd-tip2" style={{ left: tip.x + 14, top: tip.y + 14 }}>
          {tip.lines.map((l, i) => <div key={i} className={i === 0 ? "h" : undefined}>{l}</div>)}
        </div>
      )}
    </>
  );
}
