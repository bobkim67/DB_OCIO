# -*- coding: utf-8 -*-
"""Market snapshot injector — 시장 레벨 hard fact 는 DB(SCIP) source of truth.

wiki_from_naver_research. 리서치/뉴스 claim 은 방향성·해석만, 정확한 지수/가격/환율
레벨은 여기서 DB 로 주입한다(월초/월말/월중고점/월중저점/월간수익률). 리서치 pool 의
정밀 레벨 약점([[reference_salience_pool_time_bias]]) 보완.

★ dataseries gotcha: 같은 dataset 에 Price(레벨) 와 TR(총수익 rebased) 가 섞여 있어
metric 별로 (dataset_id, dataseries_id, currency_key) 를 고정해야 한다. 예: KOSPI 는
ds=15(FG Price) KRW키 = 실제 지수(8,476), ds=9(TR)=13,284 은 레벨 아님.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# metric → (dataset_id, dataseries_id, currency_key | None)
# currency_key None = blob 이 단일 숫자. 검증된 항목만 등록(오값 주입 방지).
MARKET_METRICS: dict[str, tuple[int, int, str | None]] = {
    "KOSPI":    (253, 15, "KRW"),   # ✓검증 2026-05-29 = 8,476.15
    "KOSPI200": (225, 15, "KRW"),
    "USDKRW":   (31,  6,  "USD"),   # ✓ CLAUDE.md: blob USD키 = USDKRW rate
    "Gold":     (408, 48, None),    # Gold spot (PX_LAST, 단일 숫자)
    "SP500":    (271, 6,  "USD"),   # ✓검증: FG Return USD키. 1999-12-31=1469.25=실제 S&P 종가(rebased 아님)
    "NASDAQ100":(272, 48, None),    # ✓검증: PX_LAST=레벨(1999-12-30=3683.67). ds=9 TR(37,269)는 레벨 아님—사용 금지
    "WTI":      (98,  15, "USD"),   # ✓검증: Crude Oil WTI NYM $/bbl Continuous. FG Price USD키=$/bbl(1999-12-31=25.6). 단일 ds(TR 없음)
    # 금리(yield, ds=7): % 단위라 month_return_pct 무의미(bp 변화 필요) → 별 트랙.
    # (잘못된 series 주입이 research 인용보다 위험 — 빈 값이 안전)
}


def _parse(raw: Any, key: str | None) -> float | None:
    s = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    s = s.strip()
    try:
        if s.startswith("{"):
            o = json.loads(s)
            if isinstance(o, dict):
                v = o.get(key) if key else next(iter(o.values()))
                return float(v) if v is not None else None
        return float(s.replace(",", ""))
    except (ValueError, TypeError, StopIteration):
        return None


def _load_series(metric: str, month: str) -> list[tuple[str, float]]:
    """월별 (date, level) 시계열 (effective 만, 정렬)."""
    if metric not in MARKET_METRICS:
        return []
    did, dsid, key = MARKET_METRICS[metric]
    from market_research.core.db import get_conn
    conn = get_conn("SCIP")
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT DATE(timestamp_observation) d, data FROM back_datapoint
               WHERE dataset_id=%s AND dataseries_id=%s
                 AND timestamp_observation >= %s AND timestamp_observation < %s
                 AND timestamp_ineffective IS NULL
               ORDER BY timestamp_observation""",
            (did, dsid, f"{month}-01", _next_month(month)))
        out: list[tuple[str, float]] = []
        for r in cur.fetchall():
            v = _parse(r["data"], key)
            if v is not None:
                out.append((str(r["d"]), v))
        return out
    finally:
        conn.close()


def _next_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + 1}-01-01" if m == 12 else f"{y}-{m + 1:02d}-01"


def market_snapshot(metric: str, month: str) -> dict[str, Any] | None:
    """metric 의 월초/월말/월중고점/월중저점/월간수익률. 데이터 없으면 None."""
    series = _load_series(metric, month)
    if not series:
        return None
    start, end = series[0], series[-1]
    hi = max(series, key=lambda x: x[1])
    lo = min(series, key=lambda x: x[1])
    ret = (end[1] / start[1] - 1) * 100 if start[1] else None
    return {
        "metric": metric, "month": month, "n_days": len(series),
        "month_start": {"date": start[0], "level": round(start[1], 2)},
        "month_end": {"date": end[0], "level": round(end[1], 2)},
        "month_high": {"date": hi[0], "level": round(hi[1], 2)},
        "month_low": {"date": lo[0], "level": round(lo[1], 2)},
        "month_return_pct": round(ret, 2) if ret is not None else None,
        "source": f"SCIP.back_datapoint dataset={MARKET_METRICS[metric][0]} "
                  f"ds={MARKET_METRICS[metric][1]}",
    }


def all_snapshots(month: str) -> dict[str, dict]:
    """등록된 모든 metric 의 월간 snapshot."""
    out = {}
    for m in MARKET_METRICS:
        s = market_snapshot(m, month)
        if s:
            out[m] = s
    return out


def is_market_metric_text(text: str) -> bool:
    """문장이 시장 레벨/지수 hard fact 를 담는지 (hard fact checker DB-priority 판정용)."""
    kw = ("코스피", "kospi", "코스닥", "s&p", "나스닥", "nasdaq", "지수",
          "환율", "원/달러", "달러", "유가", "금값", "금 가격", "다우")
    t = text.lower()
    return any(k in t for k in kw)


# ─────────────────────────────────────────────────────────────────
# 기준금리(정책금리) accessor — SCIP 아님. macro indicators 캐시(FRED/ECOS) 소스.
# 10년물 yield 는 곡선 왜곡이 있어 미주입; 기준금리는 단일 명확값이라 hard-fact anchor 적합.
# 수집은 외부망 배치(daily_update Step 0). 기업망(in-env)은 캐시 파일 의존 + 월간 시리즈 lag.
# ─────────────────────────────────────────────────────────────────
_MACRO_JSON = Path(__file__).resolve().parent.parent / "data" / "macro" / "indicators.json"

# source → (indicators.json group, [keys]). FED 는 target range(upper/lower).
POLICY_RATES: dict[str, tuple[str, list[str]]] = {
    "BOK": ("ecos", ["BOK_RATE"]),          # ECOS 722Y001 (월간)
    "FED": ("fred", ["FED_UPPER", "FED_LOWER"]),  # DFEDTARU/DFEDTARL (일간 target range)
    "ECB": ("fred", ["ECB_RATE"]),          # ECBDFR (일간)
    "BOJ": ("fred", ["BOJ_RATE"]),          # IRSTCI01JPM156N (월간)
}
_RATE_ORIGIN = {"BOK": "ECOS 722Y001", "FED": "FRED DFEDTARU/DFEDTARL",
                "ECB": "FRED ECBDFR", "BOJ": "FRED IRSTCI01JPM156N"}


def _load_macro() -> dict | None:
    try:
        return json.loads(_MACRO_JSON.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def _pick_latest_on_or_before(series: dict, cutoff: str) -> tuple[str, float] | None:
    """series={date:val}, cutoff 'YYYY-MM-DD'(exclusive) 이전 최신 (date<cutoff)."""
    picked = None
    for dt, v in series.items():
        if dt < cutoff and (picked is None or dt > picked[0]):
            picked = (dt, float(v))
    return picked


def _pick_policy_rate(data: dict, source: str, month: str) -> dict | None:
    """순수함수: indicators.json dict 에서 month 말 기준 정책금리. 없으면 None."""
    src = source.upper()
    if src not in POLICY_RATES or not data:
        return None
    grp, keys = POLICY_RATES[src]
    cutoff = _next_month(month)  # 'YYYY-MM-01' (해당 월 포함, 다음 월 미만)
    picks = {}
    for k in keys:
        series = (data.get(grp, {}).get(k) or {}).get("data") or {}
        p = _pick_latest_on_or_before(series, cutoff)
        if p:
            picks[k] = p
    if src == "FED":
        up = picks.get("FED_UPPER")
        if not up:
            return None
        lo = picks.get("FED_LOWER")
        return {"source": "FED", "month": month, "kind": "policy_rate", "unit": "%",
                "rate": up[1], "range": [lo[1] if lo else None, up[1]],
                "as_of": up[0], "stale_days_to_month_end": _stale_days(up[0], month),
                "origin": f"{_RATE_ORIGIN['FED']} (macro indicators cache)"}
    p = picks.get(keys[0])
    if not p:
        return None
    return {"source": src, "month": month, "kind": "policy_rate", "unit": "%",
            "rate": p[1], "range": None, "as_of": p[0],
            "stale_days_to_month_end": _stale_days(p[0], month),
            "origin": f"{_RATE_ORIGIN[src]} (macro indicators cache)"}


def _stale_days(as_of: str, month: str) -> int:
    """as_of(YYYY-MM-DD) 와 month 말일 사이 일수 (월간 시리즈 lag 표시용)."""
    from datetime import date
    y, m = int(month[:4]), int(month[5:7])
    nxt = _next_month(month)
    end = date(int(nxt[:4]), int(nxt[5:7]), 1)
    end = date.fromordinal(end.toordinal() - 1)  # month 마지막 날
    ao = date.fromisoformat(as_of)
    return max(0, (end - ao).days)


def policy_rate(source: str, month: str) -> dict | None:
    """기준금리(정책금리) — macro indicators 캐시에서 month 말 기준 최신값.

    source: 'BOK'(한은) / 'FED'(연준 target range) / 'ECB' / 'BOJ'. SCIP 아님.
    캐시 미존재/미수집 시 None (조용히 빈 값 — 오값 주입보다 안전).
    """
    return _pick_policy_rate(_load_macro() or {}, source, month)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Market snapshot (DB source of truth)")
    ap.add_argument("month")
    ap.add_argument("--metric", default=None)
    ap.add_argument("--policy", default=None, help="기준금리 source: BOK/FED/ECB/BOJ")
    args = ap.parse_args()
    if args.policy:
        r = policy_rate(args.policy, args.month)
        print(json.dumps(r, ensure_ascii=False, indent=2) if r else "no data")
    elif args.metric:
        s = market_snapshot(args.metric, args.month)
        print(json.dumps(s, ensure_ascii=False, indent=2) if s else "no data")
    else:
        for m, s in all_snapshots(args.month).items():
            print(f"{m}: 월초 {s['month_start']['level']} → 월말 {s['month_end']['level']} "
                  f"(고 {s['month_high']['level']}/저 {s['month_low']['level']}, "
                  f"{s['month_return_pct']:+.2f}%) [{s['month_end']['date']}]")
        for src in ("BOK", "FED", "ECB", "BOJ"):
            r = policy_rate(src, args.month)
            if r:
                rng = f" (range {r['range'][0]}~{r['range'][1]})" if r.get("range") else ""
                stale = f", lag {r['stale_days_to_month_end']}d" if r["stale_days_to_month_end"] else ""
                print(f"{src} 기준금리: {r['rate']}%{rng} [{r['as_of']}{stale}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
