import type { BrinsonDailyPointDTO } from "../../api/endpoints";
import { computeBrinsonMetrics } from "../../lib/brinsonMetrics";

/**
 * 위험조정 성과지표 패널 — Brinson daily 시계열(ap_cum/bm_cum) 파생 (공유 lib).
 *
 * 연율화변동성·MDD·샤프비율(AP/BM) + 정보비율(IR)·트래킹에러(TE).
 * (연율화수익률은 KPI 카드 연환산으로 이동 — 동일 소스 computeBrinsonMetrics.)
 * 252 영업일 기준 일별 시계열 파생값. 샤프=(연율화수익−RF연율)/연율화변동성.
 */
function fmtPct(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  const s = v > 0 ? "+" : "";
  return `${s}${v.toFixed(digits)}%`;
}
function fmtPlain(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}%`;
}
function fmtNum(v: number, digits = 2): string {
  return Number.isFinite(v) ? v.toFixed(digits) : "—";
}

interface Props {
  daily: BrinsonDailyPointDTO[];
  hasBm: boolean;
  rfPeriod?: number | null;
}

export default function BrinsonMetricsPanel({ daily, hasBm, rfPeriod }: Props) {
  const m = computeBrinsonMetrics(daily, rfPeriod);
  if (!m.valid) return null;

  return (
    <div className="bn-sec">
      <div className="bn-head2">
        <h3>위험조정 성과지표</h3>
        <span className="sub">일별 기준·연율화(252d) · 무위험=KIS CD Index</span>
      </div>
      <div className="bn-mstrip">
        <div className="bn-mitem">
          <div className="bn-mitem-top">
            <span className="k">연율화 변동성</span>
            <span className="v num">{fmtPlain(m.apVol)}</span>
          </div>
          <div className="cmp">
            {hasBm ? <>BM <span className="num">{fmtPlain(m.bmVol)}</span></> : <span className="num">{" "}</span>}
          </div>
        </div>
        <div className="bn-mitem">
          <div className="bn-mitem-top">
            <span className="k">최대낙폭 (MDD)</span>
            <span className="v num dn">{fmtPct(m.apMdd)}</span>
          </div>
          <div className="cmp">
            {hasBm ? <>BM <span className="num">{fmtPct(m.bmMdd)}</span></> : <span className="num">{" "}</span>}
          </div>
        </div>
        <div className="bn-mitem">
          <div className="bn-mitem-top">
            <span className="k">샤프비율 <span className="bn-info" title="(연율화수익 − 무위험연율) ÷ 연율화변동성. 무위험=KIS CD Index">i</span></span>
            <span className={"v num " + (m.apSharpe < 0 ? "bad" : "ok")}>{fmtNum(m.apSharpe)}</span>
          </div>
          <div className="cmp">
            {hasBm ? <>BM <span className="num">{fmtNum(m.bmSharpe)}</span></> : <span className="num">{" "}</span>}
          </div>
        </div>
        {hasBm && (
          <>
            <div className="bn-mitem">
              <div className="bn-mitem-top">
                <span className="k">정보비율 (IR) <span className="bn-info" title="연율화 초과수익 ÷ 트래킹에러(TE)">i</span></span>
                <span className={"v num " + (m.ir < 0 ? "bad" : "ok")}>{fmtNum(m.ir)}</span>
              </div>
              <div className="cmp"><span className="num">{" "}</span></div>
            </div>
            <div className="bn-mitem">
              <div className="bn-mitem-top">
                <span className="k">트래킹에러 (TE) <span className="bn-info" title="AP−BM 일별 초과수익의 표준편차 × √252">i</span></span>
                <span className="v num">{fmtPlain(m.te)}</span>
              </div>
              <div className="cmp"><span className="num">{" "}</span></div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
