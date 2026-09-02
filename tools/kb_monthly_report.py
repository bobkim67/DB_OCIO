# -*- coding: utf-8 -*-
"""KB국민은행 투자풀(07G07) 월간 운용보고 2종 생성 (2026-08-04 사용자 지시).

발송본 2건을 **직전 발송 원본을 틀로 열어 수치만 교체**하는 방식으로 만든다.

  워드      국민은행_{YY}년{M}월 OCIO 운용 펀드 관련 코멘트_(한국투자신탁운용).docx
            틀 = 직전 **월간** 발송본 (2026-06 은 반기 특별판이라 제외)
  FactSheet (한국투자신탁운용) KB OCIO펀드 FactSheet_{YYYY}년 {M}월_양식.xlsx
            틀 = 직전 발송본

★ 두 원본 모두 사내 DRM 래핑(`<DOCUMENT SAFER`)이라 python-docx/openpyxl 로 못 연다.
  Office COM(문서보안 에이전트가 투명 복호화) 경로만 가능하다 → pywin32 필요(메인 venv).

기준 정의 (2026-08-04 사용자 확정):
  · 설정후 수익률 = **전산값**(dt.DWPM10040 opng_next_ern_rt). 워드·FactSheet 통일.
    (구 발송본은 워드 +15.44 / FactSheet 40.46 처럼 전산과 무관한 값이 들어가 있었다)
  · 워드 성과요인분해 표 = **FX 분리**(표에 FX 행이 따로 있음) · 방법1
  · FactSheet 자산군별 수익률 = **FX 포함** · 방법3 · AP수익률(Normalized)
    (6월 발송본 해외주식 3.1578 이 FX 포함 3.16 과 일치, FX 분리 0.39 와 불일치)

실행:  python -m tools.kb_monthly_report --month 2026-07
출력:  output/ 에 위 2개 파일
"""
from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SENT_DIR = BASE / 'market_research' / 'data' / 'sent_reports' / '07G07'
OUT_DIR = BASE / 'output'
FUND = '07G07'

# FactSheet 2번째 시트(타사 포함 기준가 시계열)에서 우리 펀드 열
_FS_NAV_COL = 8            # H열 = 한국투자OCIO알아서
_XL_EPOCH = date(1899, 12, 30)

# FactSheet 자산군 6분류 — 양식 C2:H2 순서 그대로. 라벨이 아니라 **순서가 곧 정확도**다.
FS_ASSETS = ('국내주식', '해외주식', '국내채권', '해외채권', '대체투자', '유동성')
# FactSheet 운용수익률 행의 다기간 열(I~N). 설정후(O)는 ret['si'] 를 쓴다.
FS_TRAIL = ('3M', '6M', '12M', '18M', '24M', '30M')
# 해외채권 환헤지비율(FactSheet AC9) — **편입하면 해당 건을 전액 환헤지**하는 것이
# 운용 규약이라 상수다. 비중 0 이어도 100 으로 적는다 (2026-09-02 사용자 확정).
FS_BOND_HEDGE_PCT = 100.0


# ══════════════════════════════════════════
# 1) 데이터 수집
# ══════════════════════════════════════════

def _month_range(period: str) -> tuple[date, date]:
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _dt_official(end: date) -> dict:
    """전산 기간수익률 (dt.DWPM10040, fund_bm_ds_cd='F')."""
    import pandas as pd
    from modules.data_loader import get_pandas_connection
    conn = get_pandas_connection('dt')
    try:
        df = pd.read_sql(
            "SELECT mm1_ern_rt, bgyr_next_ern_rt, opng_next_ern_rt FROM DWPM10040 "
            "WHERE fund_cd=%s AND imc_cd='003228' AND fund_bm_ds_cd='F' AND std_dt=%s",
            conn, params=[FUND, end.strftime('%Y%m%d')])
    finally:
        conn.close()
    if df.empty:
        raise RuntimeError(f'전산 기간수익률 없음: {FUND} {end}')
    r = df.iloc[0]
    return {'m1': float(r.mm1_ern_rt), 'ytd': float(r.bgyr_next_ern_rt),
            'si': float(r.opng_next_ern_rt)}


def _pa_weights(start: date, end: date) -> dict:
    """PA 비중(%) 4분류 — 주식/채권/대체/유동성. 유동성은 잔여(100 − Σ).

    ★ 2026-08-04 사용자 확정: 워드·FactSheet 모두 **PA 비중**으로 통일한다.
      · PA 비중 = 조정_평가시가평가액 / (순자산T-1 + 순설정)  — 브린슨 기여와 같은 분모
      · 현금·예금은 손익 소스(MA000410)에 라인이 없어 안 잡히고 합이 100% 에 미달 →
        7월 발송본과 동일하게 **유동성 = 100 − Σ(나머지)** 로 채워 100% 를 맞춘다.
      (기말 보유 스냅샷과는 보통 0.0x%p 차이지만 현금이 쌓인 달엔 0.5~0.7%p 벌어진다.)
    FX 는 오버레이라 4분류에 넣지 않는다 → fx_split=False 로 접어서 가져온다.
    """
    from api.services.brinson_service import build_brinson
    b = build_brinson(FUND, start_date=start, end_date=end,
                      fx_split=False, mapping_method='방법1')
    g = {'주식': 0.0, '채권': 0.0, '대체': 0.0, '유동성': 0.0}
    for a in b.asset_rows:
        ac = a.asset_class
        if ac.startswith('유동성'):
            continue                      # 잔여로 채운다
        k = ('주식' if '주식' in ac else '채권' if '채권' in ac
             else '대체' if '대체' in ac else '유동성')
        g[k] += float(a.ap_weight)
    g['유동성'] = max(0.0, 100.0 - g['주식'] - g['채권'] - g['대체'])
    return g


def _pa_weights6(start: date, end: date) -> dict:
    """FactSheet A3:H3 — 같은 PA 비중을 **6분류**로. 워드 표5(4분류)와 값 출처는 같다.

    워드는 주식/채권을 국내·해외 묶어서 쓰고 FactSheet 는 갈라 쓴다.
    ★ **방법3** 이라야 6분류가 나온다 — 방법1 은 주식/채권으로 접혀서(국내·해외 구분이
      없어) FactSheet C3~F3 을 채울 수 없다. FactSheet 자산군 수익률도 방법3 이라
      비중·수익률이 같은 매핑 위에 놓인다. 실측(2026-07): 21.39/18.54/59.28/0.00 =
      발송본 C3:F3 과 일치.
    유동성은 여기서도 잔여(100 − Σ) — 현금·예금이 MA000410 에 없다.
    """
    from api.services.brinson_service import build_brinson
    b = build_brinson(FUND, start_date=start, end_date=end,
                      fx_split=False, mapping_method='방법3')
    g = {k: 0.0 for k in FS_ASSETS}
    for a in b.asset_rows:
        ac = a.asset_class
        if ac.startswith('유동성'):
            continue                      # 잔여로 채운다
        k = '대체투자' if '대체' in ac else ac
        if k in g:
            g[k] += float(a.ap_weight)
    g['유동성'] = max(0.0, 100.0 - sum(g[k] for k in FS_ASSETS[:-1]))
    return g


def _bm_series(start_date: str):
    """BM 기준가 시계열 — 대시보드와 같은 소스(DT BM 우선 → SCIP composite)."""
    import pandas as pd
    from api.services.overview_service import _load_bm_series

    df, _src = _load_bm_series(FUND, start_date)
    if df is None or len(df) == 0 or 'value' not in df.columns:
        return None
    df = df.sort_values('기준일자')
    return pd.Series(df['value'].astype(float).values,
                     index=pd.to_datetime(df['기준일자']))


def _bm_metrics(end: date, periods: list[str]) -> dict:
    """FactSheet BM 행(I16~N16 · W16 · X16) — 다기간 수익률 + 변동성/수정샤프.

    ⚠ 대시보드의 `overview_service._compute_bm_period_returns` 는 1M/3M/6M/1Y/YTD/SI
      만 낸다. FactSheet 는 **18M/24M/30M 과 BM 변동성·수정샤프**까지 필요한데, 그
      함수의 키 집합은 `api/tests/test_overview_smoke.py` 가 고정하고 있다(늘리면
      대시보드 계약이 바뀐다) → 같은 BM 시계열에 펀드와 **같은 주간수익률 규약**
      (`_build_weekly_returns` · `_calc_ref_dates`)을 적용해 여기서 따로 계산한다.

    반환: {'ret': {기간: %}, 'vol': %, 'sharpe': float}
    """
    import numpy as np
    import pandas as pd
    from modules.data_loader import (
        _build_weekly_returns, _calc_ref_dates, _lookup_price,
        compute_adjusted_sharpe_ratio, compute_rf_annualized_metrics,
        compute_sharpe_ratio, get_business_days, load_holiday_calendar,
        load_korea_holidays_weekday,
    )

    s = _bm_series('20190101')
    if s is None or len(s) == 0:
        return {}
    end_dt = pd.Timestamp(end)
    s = s[s.index <= end_dt]
    if len(s) == 0:
        return {}

    bdays = get_business_days(load_holiday_calendar())
    weekly = _build_weekly_returns(nav_series=s, dates=pd.DatetimeIndex(s.index),
                                   korea_holidays=load_korea_holidays_weekday())
    price_df = weekly[['기준일자', '기준가']].drop_duplicates(
        '기준일자').set_index('기준일자')
    end_price = _lookup_price(price_df, end_dt)
    refs = _calc_ref_dates(end_dt, list(periods), bdays)

    out: dict = {'ret': {}}
    for name, ref in refs.items():
        if pd.isna(ref):
            continue
        ref_price = _lookup_price(price_df, ref)
        if np.isnan(ref_price) or np.isnan(end_price) or ref_price == 0:
            continue
        out['ret'][name] = (end_price / ref_price - 1.0) * 100.0

    # 변동성·수정샤프 = 연초이후 주간수익률 기준 (양식 ※ 주석과 동일 규약)
    ytd_ref = refs.get('YTD')
    if ytd_ref is not None and not pd.isna(ytd_ref):
        from modules.data_loader import _return_first_weekly_date
        first_w = _return_first_weekly_date(ytd_ref, end_dt, bdays)
        m = ((weekly['기준일자'] <= end_dt) & (weekly['기준일자'] >= first_w)
             & (weekly['weekday'] == end_dt.weekday()))
        rets = weekly[m]['주간수익률'].dropna().values
        if len(rets) > 1:
            vol = float(np.std(rets, ddof=1) * np.sqrt(52))
            days = (end_dt - ytd_ref).days
            ann = ((1 + out['ret']['YTD'] / 100.0) ** (365.25 / days) - 1.0
                   if days > 0 else np.nan)
            rf = compute_rf_annualized_metrics(
                end_dt.strftime('%Y%m%d'), periods=['YTD'],
            )['annualized_return'].get('YTD', np.nan)
            out['vol'] = vol * 100.0
            out['sharpe'] = compute_sharpe_ratio(ann, vol, rf)          # 참고(일반)
            out['sharpe_adj'] = compute_adjusted_sharpe_ratio(ann, vol, rf)
    return out


def _duration_hedge(end: date, bond_w: float) -> dict:
    """FactSheet Y9·Z9(듀레이션) · AA9~AD9(환헤지비율) — 보유 스냅샷 기준.

    ★ 펀드듀레이션(Y9)은 holdings 의 `duration_overall` 이 **아니다**.
      7월 발송본 10.49300 = 채권듀레이션(**반올림 17.7**) × 국내채권 **PA 비중**
      (59.2825%). holdings 쪽은 보유 스냅샷 비중(58.55%)으로 눌러 10.356 이 나온다
      — 표 안에서 비중 기준이 갈리므로 PA 비중으로 통일한다(비중 칸과 같은 소스).
    """
    from api.services.holdings_service import build_holdings

    h = build_holdings(FUND, lookthrough=True, as_of_date=end.isoformat())
    ds = getattr(h, 'duration_summary', None)
    fx = getattr(h, 'fx_hedge', None)
    bond = round(float(ds.duration_bond), 1) if ds and ds.duration_bond else None
    return {
        'bond': bond,
        'fund': (bond * bond_w / 100.0) if bond is not None else None,
        'hedge_all': (float(fx.hedge_ratio) * 100.0) if fx else None,
    }


def _adj_sharpe(st: dict) -> float:
    """stats 한 기간의 성분(연환산·위험·무위험)으로 **수정샤프**를 낸다."""
    from modules.data_loader import compute_adjusted_sharpe_ratio
    return compute_adjusted_sharpe_ratio(
        st.get('annualized_return'), st.get('annualized_risk'),
        st.get('rf_annualized_return'))


def _prev_month_end(d: date) -> date:
    first = d.replace(day=1)
    return first - timedelta(days=1)


def collect(period: str) -> dict:
    """워드·FactSheet 치환에 필요한 값 일괄 산출."""
    from api.services.brinson_service import build_brinson
    from api.services.overview_service import build_period_returns
    from modules.data_loader import compute_full_performance_stats

    s, e = _month_range(period)
    off = _dt_official(e)

    # 성과요인분해 (워드) — FX 분리 · 방법1
    b1 = build_brinson(FUND, start_date=s, end_date=e, fx_split=True, mapping_method='방법1')
    factors, tot = {}, {'alloc': 0.0, 'select': 0.0, 'other': 0.0}
    for a in b1.asset_rows:
        key = ('유동성 및 비용' if a.asset_class.startswith('유동성') else a.asset_class)
        factors[key] = {'alloc': a.alloc_effect, 'select': a.select_effect,
                        'other': a.cross_effect,
                        'sum': a.alloc_effect + a.select_effect + a.cross_effect}
        tot['alloc'] += a.alloc_effect
        tot['select'] += a.select_effect
        tot['other'] += a.cross_effect
    tot['sum'] = tot['alloc'] + tot['select'] + tot['other']
    # 자산군 기여 (본문 '주식/채권 … 기여', '환기여수익률')
    contrib = {a.asset_class: a.contrib_return for a in b1.asset_rows}

    # BM 대비 (전산 BM 행이 비어 있어 FUND_BM 합성으로 계산)
    prt = build_period_returns(FUND, e.isoformat()).model_dump()
    bm = prt.get('bm_period_returns') or {}
    bm_1m = (bm.get('1M') or 0.0) * 100.0
    bm_ytd = (bm.get('YTD') or 0.0) * 100.0

    # FactSheet 자산군별 수익률 — FX 포함 · 방법3
    def _norm(start_d: date) -> dict:
        br = build_brinson(FUND, start_date=start_d, end_date=e,
                           fx_split=False, mapping_method='방법3')
        out = {a.asset_class: a.ap_return for a in br.asset_rows}
        out['_bm'] = {a.asset_class: a.bm_return for a in br.asset_rows}
        return out

    ytd_start = date(e.year, 1, 1)
    fs_1m, fs_ytd = _norm(s), _norm(ytd_start)

    # 다기간 수익률 + 위험지표
    stats = compute_full_performance_stats(
        FUND, end_date=e.strftime('%Y%m%d'),
        periods=['3M', '6M', '12M', '18M', '24M', '30M', 'YTD'])['periods']

    _ps = _prev_month_end(s)
    w_now = _pa_weights(s, e)
    w_prev = _pa_weights(_ps.replace(day=1), _ps)
    w6 = _pa_weights6(s, e)                      # FactSheet 비중 (6분류)
    bm_ext = _bm_metrics(e, list(FS_TRAIL) + ['YTD'])   # FactSheet BM 행
    # 설정후 BM(O16)은 `_calc_ref_dates` 가 다루지 않는 앵커 기준 —
    # 펀드 O9(ret['si'])와 같은 소스인 build_period_returns 의 SI 를 쓴다.
    if bm.get('SI') is not None:
        bm_ext.setdefault('ret', {})['SI'] = float(bm['SI']) * 100.0
    dur = _duration_hedge(e, w6['국내채권'])
    saa = {'주식': 0.0, '채권': 0.0, '대체': 0.0, '유동성': 0.0}
    for c in (b1.bm_components or []):
        k = ('주식' if '주식' in c.asset_class else '채권' if '채권' in c.asset_class
             else '대체' if '대체' in c.asset_class else '유동성')
        saa[k] += float(c.weight)

    return {
        'period': period, 'start': s, 'end': e,
        # ★ 설정후 = **앵커 기준**(build_period_returns SI, 07G07 설정 앵커 2022-01-03).
        #   2026-08-04 사용자 확정 — 7월 발송 FactSheet O9=30.1466 이 이 값이다.
        #   전산(DWPM10040 opng_next_ern_rt)은 기준가 1000 기준이라 32.69 로 다르다.
        #   1M/YTD 는 전산과 소수 2자리까지 같아 어느 쪽을 써도 동일 → 계산값으로 통일.
        'ret': {'m1': (prt['period_returns'].get('1M') or 0.0) * 100.0,
                'ytd': (prt['period_returns'].get('YTD') or 0.0) * 100.0,
                'si': (prt['period_returns'].get('SI') or 0.0) * 100.0,
                'si_jeonsan': off['si'],          # 대조용(발송본엔 미사용)
                'm1_ex': (prt['period_returns'].get('1M') or 0.0) * 100.0 - bm_1m,
                'ytd_ex': (prt['period_returns'].get('YTD') or 0.0) * 100.0 - bm_ytd,
                'bm_m1': bm_1m, 'bm_ytd': bm_ytd},
        'factors': factors, 'factor_total': tot, 'contrib': contrib,
        'weights': w_now, 'weights_prev': w_prev, 'saa': saa,
        'multi': {k: (v.get('period_return') or 0.0) * 100.0 for k, v in stats.items()},
        # ★ FactSheet W/X 열은 '수정샤프' — 초과가 음수면 위험을 **곱한다**(R 정의).
        #   일반 샤프는 대조용으로만 남긴다(크기가 전혀 다르다).
        'risk': {'vol': (stats['YTD'].get('annualized_risk') or 0.0) * 100.0,
                 'sharpe': stats['YTD'].get('sharpe_ratio'),
                 'sharpe_adj': _adj_sharpe(stats['YTD'])},
        'fs_1m': fs_1m, 'fs_ytd': fs_ytd,
        # FactSheet 전용 — 워드 쪽은 쓰지 않는다(추가만, 기존 키 불변)
        'weights6': w6, 'bm_ext': bm_ext, 'duration': dur,
    }


def _fmt(v: float, sign: bool = True, nd: int = 2) -> str:
    return f'{v:+.{nd}f}' if sign else f'{v:.{nd}f}'


# ══════════════════════════════════════════
# 2) 워드 — 직전 월간 발송본을 틀로 열어 수치만 교체
# ══════════════════════════════════════════

def _latest_monthly_docx(before: str) -> tuple[Path, str]:
    """`before`(YYYY-MM) 이전의 가장 최근 **월간** 워드 발송본 경로 + 그 기간.

    2026-06 은 '상반기 운용성과' 반기 특별판이라 월간 틀로 쓸 수 없다 →
    본문 첫 문단에 `'26.MM월 운용성과` 가 있는 것만 월간으로 인정한다(.txt 사이드카로 판별).
    """
    cands = []
    for d in sorted(SENT_DIR.glob('20??-??'), reverse=True):
        if d.name >= before:
            continue
        for p in d.glob('*.docx'):
            side = p.with_suffix(p.suffix + '.txt')
            if not side.exists():
                continue
            head = side.read_text(encoding='utf-8', errors='ignore')[:120]
            if '월 운용성과' in head and '상반기' not in head and '하반기' not in head:
                cands.append((d.name, p))
                break
    if not cands:
        raise RuntimeError(f'{before} 이전 월간 워드 발송본을 찾지 못했습니다')
    period, path = cands[0]
    return path, period


_WD = '월화수목금토일'


def _issue_date_pair(tpl: Path, today: date) -> list[tuple[str, str]]:
    """발행일 교체쌍 — 틀의 `YYYY.M.D(요일)` → 생성일(=다운로드 시점, 사용자 지시).

    틀의 날짜 토큰은 .txt 사이드카에서 정규식으로 뽑는다(원본을 다시 COM 으로 열 필요 없음).
    """
    import re
    side = tpl.with_suffix(tpl.suffix + '.txt')
    if not side.exists():
        return []
    head = side.read_text(encoding='utf-8', errors='ignore')[:200]
    m = re.search(r'\d{4}\.\d{1,2}\.\d{1,2}\([월화수목금토일]\)', head)
    if not m:
        return []
    new = f'{today.year}.{today.month}.{today.day}({_WD[today.weekday()]})'
    return [(m.group(0), new)]


def _repl_map(d: dict, tpl_period: str) -> list[tuple[str, str]]:
    """(찾을 문자열, 바꿀 문자열) — 틀(tpl_period) 기준 라벨/기간 표기 교체.

    수치 자체는 표 셀로 직접 쓰므로(_write_tables) 여기서는 **기간 라벨만** 다룬다.
    본문 수치는 문장 구조가 매월 달라 자동 치환이 위험해 별도 문단 교체로 처리한다.
    """
    ty, tm = int(tpl_period[:4]), int(tpl_period[5:7])
    y, m = d['end'].year, d['end'].month
    pm = _prev_month_end(d['start'])
    return [
        (f"'{ty % 100:02d}.{tm:02d}월 운용성과", f"'{y % 100:02d}.{m:02d}월 운용성과"),
        (f'{ty}년 {tm:02d}월', f'{y}년 {m:02d}월'),
        (f'{ty}년 {tm}월', f'{y}년 {m}월'),
        (f"’{ty % 100:02d}.{tm:02d}월말", f"’{y % 100:02d}.{m:02d}월말"),
        (f"’{ty % 100:02d}.{(tm - 1) or 12:02d}월말",
         f"’{pm.year % 100:02d}.{pm.month:02d}월말"),
    ]


def _replace_all(doc, pairs: list[tuple[str, str]]) -> dict:
    """문서 전 영역 문자열 치환. 반환 = {찾은문자열: 치환건수}.

    ⚠ `doc.Content.Find` 만 쓰면 **본문 스토리만** 훑는다 — 제목이 도형/텍스트박스에
    들어 있으면 조용히 누락된다(2026-08-04 실측: 제목 `'26.05월` 미교체).
    → StoryRanges 전체 + NextStoryRange 체인 + Shapes 텍스트프레임까지 순회한다.
    """
    hits = {s: 0 for s, _ in pairs}

    def _run(rng) -> None:
        for src, dst in pairs:
            if src == dst:
                continue
            f = rng.Find
            f.ClearFormatting()
            f.Replacement.ClearFormatting()
            # ⚠ pywin32 에서 Find.Execute(FindText=..., ReplaceWith=..., Replace=2) 처럼
            #   키워드로 넘기면 **조용히 아무것도 안 한다**(2026-08-04 실측: 반환 False,
            #   문서 무변화). 속성을 세팅한 뒤 Execute(Replace) 만 호출해야 동작한다.
            # Execute 는 **위치 인자**로 넘긴다:
            #   FindText, MatchCase, MatchWholeWord, MatchWildcards, MatchSoundsLike,
            #   MatchAllWordForms, Forward, Wrap, Format, ReplaceWith, Replace
            # (Replace 는 11번째. 키워드로 주면 Replace 가 바인딩되지 않아 '찾기'만 하고
            #  True 를 돌려준다 — 문서는 그대로. 2026-08-04 실측으로 확인한 함정.)
            if f.Execute(src, True, False, False, False, False,
                         True, 0, False, dst, 2):     # Wrap=wdFindStop, Replace=wdReplaceAll
                hits[src] += 1

    for story in doc.StoryRanges:
        rng = story
        while rng is not None:
            _run(rng)
            try:
                rng = rng.NextStoryRange
            except Exception:                 # noqa: BLE001
                rng = None
    for sh in doc.Shapes:
        try:
            if sh.TextFrame.HasText:
                _run(sh.TextFrame.TextRange)
        except Exception:                     # noqa: BLE001 — 텍스트 없는 도형
            pass
    return hits


def _write_tables(doc, d: dict) -> None:
    """Table3(성과요인분해) · Table4(운용수익률) · Table5(투자비중) 셀 값 교체."""
    r, f, t = d['ret'], d['factors'], d['factor_total']

    def put(tb, row, col, text):
        try:
            cell = tb.Cell(row, col)
        except Exception:                     # noqa: BLE001 — 병합 셀
            return
        cur = cell.Range.Text.replace('\r', '').replace('\x07', '')
        cell.Range.Text = text if cur.strip() != text else cur

    # Table 3 — 성과요인분해
    t3 = doc.Tables(3)
    put(t3, 2, 2, f"{r['m1']:+.2f}%")
    put(t3, 2, 3, f"{r['bm_m1']:+.2f}%")
    put(t3, 2, 4, f"{r['m1_ex']:+.2f}%")
    for i, key in enumerate(('주식', '채권', 'FX', '유동성 및 비용'), start=5):
        x = f.get(key) or {'alloc': 0.0, 'select': 0.0, 'other': 0.0, 'sum': 0.0}
        for c, k in ((2, 'alloc'), (3, 'select'), (4, 'other'), (5, 'sum')):
            put(t3, i, c, f"{x[k]:+.2f}%")
    for c, k in ((2, 'alloc'), (3, 'select'), (4, 'other'), (5, 'sum')):
        put(t3, 9, c, f"{t[k]:+.2f}%")

    # Table 4 — 운용수익률 (설정후 = 전산값)
    t4 = doc.Tables(4)
    for c, v in ((3, r['m1']), (4, r['m1_ex']), (5, r['ytd']),
                 (6, r['ytd_ex']), (7, r['si'])):
        put(t4, 4, c, f'{v:+.2f}')

    # Table 5 — 투자비중 (R3=SAA 대비 / R6=전월 대비)
    t5 = doc.Tables(5)
    w, wp, saa = d['weights'], d['weights_prev'], d['saa']
    keys = ('주식', '채권', '대체', '유동성')
    for row, base in ((3, saa), (6, wp)):
        for i, k in enumerate(keys):
            put(t5, row, 3 + i, f'{w[k]:.1f}')
            put(t5, row, 7 + i, f'{w[k] - base[k]:+.1f}')


def build_docx(period: str, data: dict | None = None,
               out_dir: Path | None = None) -> Path:
    """직전 월간 발송본을 복사해 수치를 교체한 워드 생성. 반환 = 생성 경로."""
    import pythoncom
    import win32com.client as win32

    d = data or collect(period)
    tpl, tpl_period = _latest_monthly_docx(period)
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    y, m = d['end'].year, d['end'].month
    out = out_dir / f'국민은행_{y % 100:02d}년{m}월 OCIO 운용 펀드 관련 코멘트_(한국투자신탁운용).docx'

    pythoncom.CoInitialize()
    app = win32.DispatchEx('Word.Application')
    app.Visible = False
    app.DisplayAlerts = False
    doc = None
    try:
        doc = app.Documents.Open(str(tpl), ReadOnly=True)
        doc.SaveAs2(str(out), FileFormat=16)      # wdFormatXMLDocument
        pairs = _repl_map(d, tpl_period) + _issue_date_pair(tpl, date.today())
        _replace_all(doc, pairs)
        _write_tables(doc, d)
        doc.Save()
    finally:
        if doc is not None:
            doc.Close(True)
        app.Quit()
        pythoncom.CoUninitialize()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--month', required=True, help='YYYY-MM')
    ap.add_argument('--dump', action='store_true', help='수집값만 출력')
    a = ap.parse_args(argv)
    sys.path.insert(0, str(BASE))
    d = collect(a.month)
    r, f, t = d['ret'], d['factors'], d['factor_total']
    print(f"[{d['period']}] {d['start']} ~ {d['end']}")
    print(f"  1개월 {_fmt(r['m1'])} (BM대비 {_fmt(r['m1_ex'])}) · "
          f"연초 {_fmt(r['ytd'])} (BM대비 {_fmt(r['ytd_ex'])}) · 설정후(전산) {_fmt(r['si'])}")
    print('  성과요인분해  자산배분  종목선택   기타     합계')
    for k in ('주식', '채권', 'FX', '유동성 및 비용'):
        if k not in f:
            continue
        x = f[k]
        print(f"    {k:10s} {_fmt(x['alloc'])} {_fmt(x['select'])} "
              f"{_fmt(x['other'])} {_fmt(x['sum'])}")
    print(f"    {'요인별 합계':10s} {_fmt(t['alloc'])} {_fmt(t['select'])} "
          f"{_fmt(t['other'])} {_fmt(t['sum'])}")
    w, wp, saa = d['weights'], d['weights_prev'], d['saa']
    print('  비중(주식/채권/대체/유동성)')
    print('    당월  ' + ' · '.join(f'{k} {w[k]:.1f}' for k in w))
    print('    SAA대비' + ' · '.join(f' {k} {w[k]-saa[k]:+.1f}' for k in w))
    print('    전월대비' + ' · '.join(f' {k} {w[k]-wp[k]:+.1f}' for k in w))
    m = d['multi']
    print('  다기간  ' + ' · '.join(f'{k} {m[k]:+.2f}' for k in
                                   ('3M', '6M', '12M', '18M', '24M', '30M')))
    print(f"  변동성 {d['risk']['vol']:.2f} · 수정샤프 {d['risk']['sharpe']}")
    print('  FactSheet 1M 자산군수익률: ' + ' · '.join(
        f'{k} {v:+.2f}' for k, v in d['fs_1m'].items() if k != '_bm'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
