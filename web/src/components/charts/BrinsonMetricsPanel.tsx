import type { BrinsonDailyPointDTO } from "../../api/endpoints";

/**
 * 위험조정 성과지표 패널 — Brinson daily 시계열(ap_cum/bm_cum)에서 파생.
 *
 * 연율화수익률·연율화변동성·MDD(AP/BM) + 트래킹에러(TE)·정보비율(IR).
 * 252 영업일 기준 일별 시계열 파생값(시스템 R 주간 연율화와 방법 다름 → '일별 기준' 명시).
 * 샤프비율은 무위험수익률(RF) 미연동이라 제외 — 액티브 관리 핵심인 IR/TE 로 대체.
 */
const TD = 252;

// 누적수익률(%) 시계열 → 일별 수익률(분수) 배열
function dailyReturns(cumPct: number[]): number[] {
  const w = cumPct.map((c) => 1 + c / 100); // 부(wealth) 지수
  const out: number[] = [];
  for (let i = 1; i < w.length; i++) out.push(w[i] / w[i - 1] - 1);
  return out;
}
function annReturn(cumPctLast: number, n: number): number {
  if (n <= 0) return 0;
  return (Math.pow(1 + cumPctLast / 100, TD / n) - 1) * 100;
}
function stdev(xs: number[]): number {
  if (xs.length < 2) return 0;
  const m = xs.reduce((s, x) => s + x, 0) / xs.length;
  const v = xs.reduce((s, x) => s + (x - m) ** 2, 0) / (xs.length - 1);
  return Math.sqrt(v);
}
function annVol(rets: number[]): number {
  return stdev(rets) * Math.sqrt(TD) * 100;
}
// 최대낙폭(MDD, %) — 누적부 지수 기준
function mdd(cumPct: number[]): number {
  let peak = -Infinity;
  let worst = 0;
  for (const c of cumPct) {
    const w = 1 + c / 100;
    if (w > peak) peak = w;
    const dd = w / peak - 1;
    if (dd < worst) worst = dd;
  }
  return worst * 100;
}

function fmtPct(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  const s = v > 0 ? "+" : "";
  return `${s}${v.toFixed(digits)}%`;
}
function fmtPlain(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

interface Props {
  daily: BrinsonDailyPointDTO[];
  hasBm: boolean;
}

export default function BrinsonMetricsPanel({ daily, hasBm }: Props) {
  if (daily.length < 2) return null;
  const n = daily.length;
  const apCum = daily.map((d) => d.ap_cum);
  const bmCum = daily.map((d) => d.bm_cum);
  const apRet = dailyReturns(apCum);
  const bmRet = dailyReturns(bmCum);

  const apAnnRet = annReturn(apCum[n - 1], n);
  const bmAnnRet = annReturn(bmCum[n - 1], n);
  const apVol = annVol(apRet);
  const bmVol = annVol(bmRet);
  const apMdd = mdd(apCum);
  const bmMdd = mdd(bmCum);

  // 액티브: 트래킹에러 = std(AP일별 − BM일별)×√252, 정보비율 = 연율화초과 / TE
  const activeRet = apRet.map((r, i) => r - (bmRet[i] ?? 0));
  const te = stdev(activeRet) * Math.sqrt(TD) * 100;
  const annExcess = apAnnRet - bmAnnRet;
  const ir = te > 1e-9 ? annExcess / te : NaN;

  return (
    <div className="bn-sec">
      <div className="bn-head2">
        <h3>위험조정 성과지표</h3>
        <span className="sub">일별 기준·연율화(252d)</span>
      </div>
      <div className="bn-mstrip">
        <div className="bn-mitem">
          <div className="k">연율화 수익률</div>
          <div className="vrow">
            <span className={"v num " + (apAnnRet < 0 ? "dn" : "up")}>{fmtPct(apAnnRet)}</span>
            {hasBm && <span className="vb num">BM {fmtPct(bmAnnRet)}</span>}
          </div>
        </div>
        <div className="bn-mitem">
          <div className="k">연율화 변동성</div>
          <div className="vrow">
            <span className="v num">{fmtPlain(apVol)}</span>
            {hasBm && <span className="vb num">BM {fmtPlain(bmVol)}</span>}
          </div>
        </div>
        <div className="bn-mitem">
          <div className="k">최대낙폭 (MDD)</div>
          <div className="vrow">
            <span className="v num dn">{fmtPct(apMdd)}</span>
            {hasBm && <span className="vb num">BM {fmtPct(bmMdd)}</span>}
          </div>
        </div>
        {hasBm && (
          <>
            <div className="bn-mitem">
              <div className="k">초과수익 (연율)</div>
              <div className="vrow">
                <span className={"v num " + (annExcess < 0 ? "bad" : "ok")}>{fmtPct(annExcess)}</span>
              </div>
            </div>
            <div className="bn-mitem">
              <div className="k">정보비율 (IR)</div>
              <div className="vrow">
                <span className={"v num " + (ir < 0 ? "bad" : "ok")}>
                  {Number.isFinite(ir) ? ir.toFixed(2) : "—"}
                </span>
              </div>
            </div>
            <div className="bn-mitem">
              <div className="k">트래킹에러 (TE)</div>
              <div className="vrow">
                <span className="v num">{fmtPlain(te)}</span>
              </div>
            </div>
          </>
        )}
      </div>
      <div className="bn-note">
        ※ IR = 연율화 초과수익 ÷ TE. 샤프비율은 무위험수익률 미연동으로 제외.
      </div>
    </div>
  );
}
