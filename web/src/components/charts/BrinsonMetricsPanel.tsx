import type { BrinsonDailyPointDTO } from "../../api/endpoints";
import { computeBrinsonMetrics } from "../../lib/brinsonMetrics";

/**
 * 위험조정 성과지표 패널 — Brinson daily 시계열(ap_cum/bm_cum) 파생 (공유 lib).
 *
 * 변동성(연환산)·MDD·샤프비율(AP/BM) + 정보비율(IR)·트래킹에러(TE).
 * (수익률(연환산)은 KPI 카드로 이동 — 동일 소스 computeBrinsonMetrics.)
 * 리스크 지표(변동성·TE·IR·샤프 분모)는 **주간수익률 std × √52** (Overview 와 동일 기준).
 * MDD 만 일간 종가 기준(주중 저점 보존).
 * 샤프 = (수익률(연환산) − 무위험수익률(연환산)) ÷ 변동성(연환산).
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
        <span className="sub">주간수익률 기준·연환산(√52) · MDD는 일간 종가 기준 · 무위험수익률=KIS CD Index</span>
      </div>
      <div className="bn-mstrip">
        <div className="bn-mitem">
          <div className="bn-mitem-top">
            <span className="k">변동성(연환산) <span className="bn-info" title="주간수익률 표준편차 × √52">i</span></span>
            <span className="v num">{fmtPlain(m.apVol)}</span>
          </div>
          <div className="cmp">
            {hasBm ? <>BM <span className="num">{fmtPlain(m.bmVol)}</span></> : <span className="num">{" "}</span>}
          </div>
        </div>
        <div className="bn-mitem">
          <div className="bn-mitem-top">
            <span className="k">최대낙폭 (MDD) <span className="bn-info" title="일간 종가 기준 고점 대비 최대 하락폭. 주간으로 집계하면 주중 저점을 놓쳐 낙폭이 과소평가되므로 일간 유지">i</span></span>
            <span className="v num dn">{fmtPct(m.apMdd)}</span>
          </div>
          <div className="cmp">
            {hasBm ? <>BM <span className="num">{fmtPct(m.bmMdd)}</span></> : <span className="num">{" "}</span>}
          </div>
        </div>
        <div className="bn-mitem">
          <div className="bn-mitem-top">
            <span className="k">샤프비율 <span className="bn-info" title="(수익률(연환산) − 무위험수익률(연환산)) ÷ 변동성(연환산). 무위험수익률=KIS CD Index">i</span></span>
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
                <span className="k">정보비율 (IR) <span className="bn-info" title="초과수익(연환산) ÷ 트래킹에러(TE)">i</span></span>
                <span className={"v num " + (m.ir < 0 ? "bad" : "ok")}>{fmtNum(m.ir)}</span>
              </div>
              <div className="cmp"><span className="num">{" "}</span></div>
            </div>
            <div className="bn-mitem">
              <div className="bn-mitem-top">
                <span className="k">트래킹에러 (TE) <span className="bn-info" title="AP−BM 주간 초과수익의 표준편차 × √52">i</span></span>
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
