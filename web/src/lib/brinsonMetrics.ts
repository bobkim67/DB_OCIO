import type { BrinsonDailyPointDTO } from "../api/endpoints";

/**
 * Brinson daily 시계열(ap_cum/bm_cum) 파생 위험조정 성과지표 — 공유 유틸.
 *
 * KPI(연환산 인라인)와 위험지표 스트립(BrinsonMetricsPanel)이 동일 소스를 쓰도록 추출.
 * 252 영업일 기준 일별 시계열 파생값(R 주간 연율화와 방법 다름 → '일별 기준' 명시).
 * 샤프비율 = (연율화수익 − RF연율) / 연율화변동성 (RF 는 백엔드 rf_annual, %).
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

export interface BrinsonMetrics {
  valid: boolean;          // daily.length >= 2
  apAnnRet: number;        // 연율화 수익률 (%)
  bmAnnRet: number;
  annExcess: number;       // AP연율 − BM연율 (%)
  apVol: number;           // 연율화 변동성 (%)
  bmVol: number;
  apMdd: number;           // MDD (%)
  bmMdd: number;
  te: number;              // 트래킹에러 (%)
  ir: number;              // 정보비율
  apSharpe: number;        // (apAnnRet − rf) / apVol
  bmSharpe: number;
  rfAnnual: number;        // 무위험 연율(%) — null 시 0
}

const EMPTY: BrinsonMetrics = {
  valid: false, apAnnRet: NaN, bmAnnRet: NaN, annExcess: NaN,
  apVol: NaN, bmVol: NaN, apMdd: NaN, bmMdd: NaN, te: NaN, ir: NaN,
  apSharpe: NaN, bmSharpe: NaN, rfAnnual: 0,
};

export function computeBrinsonMetrics(
  daily: BrinsonDailyPointDTO[],
  rfAnnualPct?: number | null,
): BrinsonMetrics {
  if (!daily || daily.length < 2) return EMPTY;
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

  // 샤프 = (연율화수익 − RF연율) / 연율화변동성. RF 결측 시 0 (안전 처리).
  const rf = rfAnnualPct ?? 0;
  const apSharpe = apVol > 1e-9 ? (apAnnRet - rf) / apVol : NaN;
  const bmSharpe = bmVol > 1e-9 ? (bmAnnRet - rf) / bmVol : NaN;

  return {
    valid: true, apAnnRet, bmAnnRet, annExcess,
    apVol, bmVol, apMdd, bmMdd, te, ir, apSharpe, bmSharpe, rfAnnual: rf,
  };
}
