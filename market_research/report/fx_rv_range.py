# -*- coding: utf-8 -*-
"""원/달러 환헤지 레인지 — DXY 대비 원화 상대가치(RV) 기준 (2026-08-06 사용자 지시).

전제: **DXY 가 현 수준을 유지**한다고 보고, 스프레드(로그 상대가치)가 롤링1Y 분포의
어디까지 움직이는지로 환율 레인지를 잡는다.

    S(t) = 100 × [ ln(DXY_t / DXY_0) − ln(USDKRW_t / USDKRW_0) ]      (%, 지수화)

DXY 고정이면 S 의 변화는 곧 원화의 변화다:

    USDKRW(S*) = USDKRW_now × exp( −(S* − S_now) / 100 )

S 가 커지면(달러 대비 원화가 상대적으로 강해지면) 환율은 내려간다.
따라서 **+2σ = 레인지 하단(원화 강세), μ = 레인지 상단**이다.

★ 정의는 사내 `글로벌 마켓 모니터`(192.168.199.78:8010) → 알파페어 → 원화 RV →
  롤링1Y · 로그 와 **동일**하다. 2026-08-05 기준 화면값
  (현재 상대가치 +1.50% · z=+1.56σ)을 이 코드가 +1.501% · +1.561σ 로 재현한다.
  시리즈도 그 화면과 같은 **dataseries_id=48** 을 쓴다(6 번은 관측 수가 달라
  σ 가 어긋난다 — 105/6 은 1999년부터라 4,125 vs 6,939).
"""
from __future__ import annotations

import math

# 화면(알파페어)과 같은 계열 — DXY: dataset 105, USDKRW: dataset 31, 둘 다 ds 48
_DXY = (105, 48)
_USDKRW = (31, 48)
_WINDOW = 252          # 롤링1Y = 직전 252 영업일
_ROUND = 10            # 표기 단위 — 10원 (2026-08-06 사용자 확정)


def _series(dataset_id: int, ds_id: int) -> dict:
    from market_research.core.db import get_conn, parse_blob
    conn = get_conn('SCIP')
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT DATE(timestamp_observation) AS d, data FROM back_datapoint '
            'WHERE dataset_id=%s AND dataseries_id=%s ORDER BY timestamp_observation',
            (dataset_id, ds_id))
        out = {}
        for row in cur.fetchall():
            v = parse_blob(row['data'])
            if isinstance(v, dict):
                v = v.get('USD')
            if v is not None:
                out[str(row['d'])] = float(v)
        return out
    finally:
        conn.close()


def compute(asof: str) -> dict | None:
    """`asof`('YYYY-MM-DD') 기준 RV 분포 → 환율 레인지 후보.

    Returns `{'asof','spot','z','mu','sd','levels':{...},'range_mu_2s','range_pm_2s'}`
    또는 데이터 부족 시 None.
    """
    dxy, krw = _series(*_DXY), _series(*_USDKRW)
    dates = sorted(set(dxy) & set(krw))
    if len(dates) < _WINDOW + 1:
        return None
    prior = [d for d in dates if d <= asof]
    if not prior:
        return None
    i = len(prior) - 1

    a0, b0 = dxy[dates[0]], krw[dates[0]]
    s = [100 * (math.log(dxy[d] / a0) - math.log(krw[d] / b0)) for d in dates]

    win = s[max(0, i - _WINDOW + 1): i + 1]
    mu = sum(win) / len(win)
    sd = (sum((x - mu) ** 2 for x in win) / (len(win) - 1)) ** 0.5
    if sd <= 0:
        return None

    spot, cur = krw[dates[i]], s[i]

    def level(target: float) -> float:
        return spot * math.exp(-(target - cur) / 100)

    def rng(lo_t: float, hi_t: float) -> tuple[int, int]:
        # target 이 클수록 환율이 낮다 → lo(환율 하단) = 큰 target
        lo = int(round(level(hi_t) / _ROUND) * _ROUND)
        hi = int(round(level(lo_t) / _ROUND) * _ROUND)
        return lo, hi

    return {
        'asof': dates[i], 'spot': round(spot, 2), 'dxy': round(dxy[dates[i]], 3),
        'cur': round(cur, 3), 'mu': round(mu, 3), 'sd': round(sd, 3),
        'z': round((cur - mu) / sd, 2),
        'levels': {k: round(level(v), 1) for k, v in
                   (('mu', mu), ('+1s', mu + sd), ('+2s', mu + 2 * sd),
                    ('-1s', mu - sd), ('-2s', mu - 2 * sd))},
        # ★ 채택 구간 = **±2σ** (2026-08-06 사용자 확정). μ~+2σ 는 폭이 60원대라
        #   발송본 관행(80원)보다 좁았다.
        'range_pm_2s': rng(mu - 2 * sd, mu + 2 * sd),
        # 참고: 평균 ~ +2σ (좁은 판본)
        'range_mu_2s': rng(mu, mu + 2 * sd),
    }
