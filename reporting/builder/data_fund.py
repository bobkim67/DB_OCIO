"""펀드 데이터 라이브 로딩 (P1) — 대시보드 DB 로더 재사용.

원본 파이프라인의 fund JSON 스냅샷을 대체: 임의 (펀드코드, 기준일) 로
NAV/BM 시계열·기간수익률·자산배분 비중을 dt/SCIP 에서 직접 생성.
"""
import datetime

import pandas as pd
from dateutil.relativedelta import relativedelta

from . import common  # noqa: F401  (sys.path 부트스트랩)
from modules.data_loader import (
    load_fund_nav_with_aum, load_dt_bm_prices, load_composite_bm_prices,
    load_weight_history_lookthrough, _FUND_INCEPTION_BASE,
    _map_bm_component_to_asset_class,
)
from config.funds import FUND_BM, FUND_META


def _anchor(df, target):
    """target 일자 이하 마지막 행 (전산 관행: 앵커 ≤ 목표일)."""
    sub = df[df['date'] <= pd.Timestamp(target)]
    return sub.iloc[-1] if len(sub) else None


def get_fund_data(fund_code: str, end_date: str, start_date: str | None = None) -> dict:
    """start_date: 보고 구간 시작 (None=전년말 YTD — 발송본 컨셉). s4/s6/s7 이 사용.

    반환 rets 에 표준 앵커(m1/m3/m6/ytd/q/si) + 구간(pr_f/pr_b = start~end) 포함.
    """
    end = pd.Timestamp(end_date)
    start_load = (end - relativedelta(months=14)).strftime('%Y%m%d')
    if start_date and pd.Timestamp(start_date) < end - relativedelta(months=13):
        start_load = (pd.Timestamp(start_date) - relativedelta(days=10)).strftime('%Y%m%d')

    # NAV
    nav = load_fund_nav_with_aum(fund_code, start_load)
    nav = nav[nav['기준일자'] <= end]
    if nav.empty:
        raise ValueError(f'{fund_code}: NAV 없음 (start={start_load}, end={end_date})')
    nav = nav.rename(columns={'기준일자': 'date', 'MOD_STPR': 'nav'})[['date', 'nav']]

    # BM: DT 우선 → SCIP composite fallback (대시보드 규약)
    bm_src = None
    bm = load_dt_bm_prices(fund_code, start_load)
    if bm is not None and len(bm):
        bm_src = 'dt'
    else:
        cfg = FUND_BM.get(fund_code)
        if cfg:
            bm = load_composite_bm_prices(cfg['components'], start_load)
            bm_src = 'scip' if bm is not None and len(bm) else None
    if bm_src:
        bm = bm.rename(columns={'기준일자': 'date', 'value': 'bm'})[['date', 'bm']]
        bm['date'] = pd.to_datetime(bm['date'])
        df = nav.merge(bm, on='date', how='inner').sort_values('date').reset_index(drop=True)
    else:
        df = nav.sort_values('date').reset_index(drop=True)
        df['bm'] = float('nan')

    asof = df['date'].iloc[-1]
    last = df.iloc[-1]

    # 기간 앵커 (relativedelta 달력 기준 — DT 전산 일치)
    y_prev_end = datetime.date(asof.year - 1, 12, 31)
    qm = (asof.month - 1) // 3 * 3          # 직전분기말 월
    q_end = (datetime.date(asof.year, qm + 1, 1) - datetime.timedelta(days=1)
             if qm else datetime.date(asof.year - 1, 12, 31))
    # 트레일링 앵커 = 같은날짜(relativedelta), 단 기준일이 월말이면 상대 월의 말일로 스냅
    # (DT DWPM10040 역산 검증 2026-07-13: 6/30 → 3M=3/31(11.516)·6M=12/31(9.858),
    #  월중 6/16 → 3M=3/16(9.048) — 같은날짜. 스냅 미적용 시 월말에서 전산과 불일치)
    _is_me = asof == asof + relativedelta(day=31)
    def _trail(n):
        t = asof - relativedelta(months=n)
        return t + relativedelta(day=31) if _is_me else t
    anchors = {
        'm1': _trail(1),
        'm3': _trail(3),
        'm6': _trail(6),
        'ytd': pd.Timestamp(y_prev_end),
        'q': pd.Timestamp(q_end),
    }
    rets = {}
    for k, tgt in anchors.items():
        a = _anchor(df, tgt)
        if a is None:
            rets[f'{k}_f'] = rets[f'{k}_b'] = None
            continue
        rets[f'{k}_f'] = round((last['nav'] / a['nav'] - 1) * 100, 2)
        rets[f'{k}_b'] = (round((last['bm'] / a['bm'] - 1) * 100, 2)
                          if bm_src and pd.notna(a['bm']) else None)

    # 설정후 (2026-07-13 사용자 확정): 실제 설정일 기준 = base 1000,
    #   승계/예외만 override(_FUND_INCEPTION_BASE: 4JM12=1970.76, 07G07=편입일 1019.5).
    #   BM 은 DT(base 1000 절대지수)일 때만 분모 1000, 07G07 은 편입일 앵커
    #   (_FUND_BM_INCEPTION_BASE 규약). composite 는 임의 리베이스라 생략.
    base = _FUND_INCEPTION_BASE.get(fund_code, 1000.0)
    _BM_SI_BASE = {'07G07': 999.55727568946}   # api.overview_service._FUND_BM_INCEPTION_BASE
    rets['si_f'] = round((last['nav'] / base - 1) * 100, 2)
    rets['si_b'] = (round((last['bm'] / _BM_SI_BASE.get(fund_code, 1000.0) - 1) * 100, 2)
                    if bm_src == 'dt' else None)

    # 보고 구간 (차트/기여수익률용): start_date 지정 시 그 앵커, 아니면 전년말(YTD)
    a_ytd = _anchor(df, anchors['ytd'])
    a_start = _anchor(df, pd.Timestamp(start_date)) if start_date else a_ytd
    if a_start is None:
        a_start = a_ytd if a_ytd is not None else df.iloc[[0]].iloc[0]
    is_ytd = a_ytd is not None and a_start['date'] == a_ytd['date']
    ser = df[df['date'] >= a_start['date']]
    series_ytd = [
        {'date': r['date'].strftime('%Y-%m-%d'), 'nav': float(r['nav']),
         'bm': (float(r['bm']) if bm_src and pd.notna(r['bm']) else None)}
        for _, r in ser.iterrows()
    ]
    # 구간 수익률 (start~end)
    rets['pr_f'] = round((last['nav'] / a_start['nav'] - 1) * 100, 2)
    rets['pr_b'] = (round((last['bm'] / a_start['bm'] - 1) * 100, 2)
                    if bm_src and pd.notna(a_start['bm']) else None)

    # 자산배분 비중 (look-through 6버킷 최신일)
    wdf, _is_fof, _keys = load_weight_history_lookthrough(
        fund_code, (end - pd.Timedelta(days=14)).strftime('%Y-%m-%d'), 'asset')
    weights = {}
    if len(wdf):
        wdf = wdf[wdf['date'] <= end.strftime('%Y-%m-%d')]
        if len(wdf):
            last_d = wdf['date'].max()
            for _, r in wdf[wdf['date'] == last_d].iterrows():
                k = {'금·대체': '대체', '유동성': '현금'}.get(r['key'], r['key'])
                weights[k] = weights.get(k, 0.0) + float(r['weight'])

    # BM 자산군 비중 (FUND_BM 컴포넌트 → 자산군 매핑)
    bm_weights = {}
    cfg = FUND_BM.get(fund_code)
    if cfg:
        for c in cfg['components']:
            cls = _map_bm_component_to_asset_class(c['name'])
            cls = {'유동성및기타': '현금', '유동성': '현금'}.get(cls, cls)
            bm_weights[cls] = bm_weights.get(cls, 0.0) + c['weight'] * 100

    return {
        'fund_code': fund_code,
        'fund_name': FUND_META.get(fund_code, {}).get('name', fund_code),
        'asof': asof.strftime('%Y-%m-%d'),
        'bm_src': bm_src,
        'series_ytd': series_ytd,             # 보고 구간 시계열 (키명 유지)
        'period_start': a_start['date'].strftime('%Y-%m-%d'),
        'ytd_start': (a_ytd['date'].strftime('%Y-%m-%d') if a_ytd is not None
                      else series_ytd[0]['date']),
        'is_ytd': is_ytd,
        'plabel': '연초 이후' if is_ytd else '기간',
        'rets': rets,
        'weights': weights,
        'bm_weights': bm_weights,
    }


# 기여수익률 자산군 → s7 표 행 매핑 (대체→대체투자, FX·유동성→기타)
_BR_BUCKET = {'국내주식': '국내주식', '해외주식': '해외주식', '국내채권': '국내채권',
              '해외채권': '해외채권', '대체': '대체투자'}


def get_brinson_contrib(fund_code: str, start_date: str, end_date: str) -> dict | None:
    """s7 기여수익률 — 대시보드 Brinson 엔진(디스크캐시) 재사용. 실패 시 None(빈칸).

    fx_split=False (2026-07-13 사용자 지시): 환효과를 자산군 수익에 포함 — FX 별도행 없음.
    """
    import datetime as _dt
    try:
        from api.services.brinson_service import build_brinson
        res = build_brinson(
            fund_code,
            start_date=_dt.date.fromisoformat(start_date),
            end_date=_dt.date.fromisoformat(end_date),
            fx_split=False,
        )
    except Exception as e:                # noqa: BLE001 — 콜드 실패 시 표만 빈칸
        print(f'[brinson] skip: {e}')
        return None
    rows = {}
    for r in res.asset_rows:
        b = _BR_BUCKET.get(r.asset_class, '기타')
        ap, bm = rows.get(b, (0.0, 0.0))
        rows[b] = (round(ap + r.contrib_return, 2), round(bm + r.bm_contrib, 2))
    return {
        'rows': rows,
        'ap_total': round(res.period_ap_return, 2),
        'bm_total': round(res.period_bm_return, 2),
    }
