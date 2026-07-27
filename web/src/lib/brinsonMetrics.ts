import type { BrinsonDailyPointDTO } from "../api/endpoints";

/**
 * Brinson daily 시계열(ap_cum/bm_cum) 파생 위험조정 성과지표 — 공유 유틸.
 *
 * KPI(연환산 인라인)와 위험지표 스트립(BrinsonMetricsPanel)이 동일 소스를 쓰도록 추출.
 *
 * ★ 리스크 지표(변동성·TE·IR·샤프 분모)는 **주간수익률 표준편차 × √52** 기준
 * (2026-07-27 사용자 지시). Overview 변동성(백엔드 compute_full_performance_stats /
 * _weekly_vol)과 동일 기준으로 통일 — 이전엔 여기만 일별 ×√252 라 두 탭 수치가 어긋났다.
 * 주간화는 백엔드 _weekly_vol 과 동일하게 **주(금요일 마감) 마지막 관측치**를 취한다.
 *
 * 수익률 연율화(annReturn)는 영업일 기준(252d) 유지 — 분자는 수익률, 분모는 리스크로
 * 서로 독립된 연율화라 혼재가 아니다. MDD 는 변동성 파생이 아니라 낙폭이므로 일별 유지
 * (주간으로 바꾸면 주중 저점을 놓쳐 낙폭이 과소평가된다).
 */
const TD = 252;
const WK = 52;

// 그 날짜가 속한 주의 '금요일 마감' 키 (pandas resample('W-FRI') 와 동일 구간)
function weekKey(iso: string): string {
  const d = new Date(iso + "T00:00:00Z");
  const dow = d.getUTCDay();               // 0=일 … 5=금 … 6=토
  const add = (5 - dow + 7) % 7;           // 다음(또는 당일) 금요일까지
  d.setUTCDate(d.getUTCDate() + add);
  return d.toISOString().slice(0, 10);
}

/** 일별 누적수익률(%) → 주간 수익률(분수) 배열. 주별 마지막 관측치 기준. */
function weeklyReturns(dates: string[], cumPct: number[]): number[] {
  const lastOfWeek = new Map<string, number>();
  for (let i = 0; i < cumPct.length; i++) {
    lastOfWeek.set(weekKey(dates[i]), 1 + cumPct[i] / 100);
  }
  const keys = [...lastOfWeek.keys()].sort();
  const out: number[] = [];
  for (let i = 1; i < keys.length; i++) {
    const prev = lastOfWeek.get(keys[i - 1])!;
    const cur = lastOfWeek.get(keys[i])!;
    if (prev > 0) out.push(cur / prev - 1);
  }
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
// 연율화 변동성 — 주간수익률 std(ddof=1) × √52
function annVol(weeklyRets: number[]): number {
  if (weeklyRets.length < 2) return NaN;
  return stdev(weeklyRets) * Math.sqrt(WK) * 100;
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
  apSharpe: number;        // (apAnnRet − rfAnn) / apVol
  bmSharpe: number;
  rfAnnual: number;        // 무위험 연율(%, 252d 기준으로 연율화) — null 시 0
}

const EMPTY: BrinsonMetrics = {
  valid: false, apAnnRet: NaN, bmAnnRet: NaN, annExcess: NaN,
  apVol: NaN, bmVol: NaN, apMdd: NaN, bmMdd: NaN, te: NaN, ir: NaN,
  apSharpe: NaN, bmSharpe: NaN, rfAnnual: 0,
};

export function computeBrinsonMetrics(
  daily: BrinsonDailyPointDTO[],
  rfPeriodPct?: number | null,
): BrinsonMetrics {
  if (!daily || daily.length < 2) return EMPTY;
  const n = daily.length;
  const apCum = daily.map((d) => d.ap_cum);
  const bmCum = daily.map((d) => d.bm_cum);
  const dates = daily.map((d) => String(d.date).slice(0, 10));
  // 리스크 지표는 주간, MDD 는 일별(주중 저점 보존)
  const apWk = weeklyReturns(dates, apCum);
  const bmWk = weeklyReturns(dates, bmCum);

  const apAnnRet = annReturn(apCum[n - 1], n);
  const bmAnnRet = annReturn(bmCum[n - 1], n);
  const apVol = annVol(apWk);
  const bmVol = annVol(bmWk);
  const apMdd = mdd(apCum);
  const bmMdd = mdd(bmCum);

  // 액티브: 트래킹에러 = std(AP주간 − BM주간)×√52, 정보비율 = 연율화초과 / TE
  const activeWk = apWk.map((r, i) => r - (bmWk[i] ?? 0));
  const te = activeWk.length >= 2 ? stdev(activeWk) * Math.sqrt(WK) * 100 : NaN;
  const annExcess = apAnnRet - bmAnnRet;
  const ir = te > 1e-9 ? annExcess / te : NaN;

  // 샤프 = (연율화수익 − RF연율) / 연율화변동성. RF 는 '기간 누적수익률' 을 AP/BM 과 동일한
  // 252d 공식으로 연율화(annReturn)해 분자/분모 기준 통일. RF 결측 시 0 (안전 처리).
  const rf = rfPeriodPct != null ? annReturn(rfPeriodPct, n) : 0;
  const apSharpe = apVol > 1e-9 ? (apAnnRet - rf) / apVol : NaN;   // 분모=주간기준 변동성
  const bmSharpe = bmVol > 1e-9 ? (bmAnnRet - rf) / bmVol : NaN;

  return {
    valid: true, apAnnRet, bmAnnRet, annExcess,
    apVol, bmVol, apMdd, bmMdd, te, ir, apSharpe, bmSharpe, rfAnnual: rf,
  };
}
