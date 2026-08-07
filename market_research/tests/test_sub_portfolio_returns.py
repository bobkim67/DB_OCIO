# -*- coding: utf-8 -*-
"""모펀드 서브 포트폴리오 수익률 — 기초일 + fund_ret 타입 계약 (2026-08-07).

두 결함이 겹쳐 07G07(포맷 K) 코멘트 생성이 500 으로 죽고 있었다.

  1. 기초일 off-by-one — `start_dt - 1일` 을 분모로 써서 전월 마지막 영업일
     하루가 더 섞였다. 실측 07G07 2026-07: 기초 6/29 → -6.68% vs
     기초 **6/30 → -7.34%**(= PA·기준가 값). [[reference_pa_period_start_offbyone]]
  2. `fund_ret` 타입 — `_adapt_compute_single_port_pa` 는 **float(%)** 를 주는데
     호출부가 dict 로 다뤄 `dict(float)` TypeError 가 났고, except 가 삼켜서
     서브 블록이 프롬프트에서 통째로 사라졌다. 포맷 K 는 한 발 더 나아가
     `fund_ret.get('sub_returns')` 를 호출해 AttributeError 로 죽었다.

LLM·DB 호출 0 (read_sql 은 monkeypatch).
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from market_research.report import fund_comment_service as svc


def _patch_db(monkeypatch, df: pd.DataFrame) -> dict:
    """read_sql 을 가로채 params 를 잡아두고 고정 DataFrame 을 돌려준다."""
    seen: dict = {}

    class _Conn:
        def close(self):
            pass

    monkeypatch.setattr(svc, '_sub_portfolio_returns',
                        svc._sub_portfolio_returns)          # 원본 유지(명시)
    monkeypatch.setattr('modules.data_loader.get_pandas_connection',
                        lambda *_a, **_k: _Conn())

    def _fake_read_sql(sql, conn, params=None):
        seen['sql'] = sql
        seen['params'] = params
        # 실제 DB 처럼 params(STD_DT) 로 거른다 — 안 그러면 기초일이 틀려도
        # 수익률 테스트가 통과해 버려 회귀를 못 잡는다.
        return df[df['STD_DT'].isin(list(params or []))].copy()

    monkeypatch.setattr(pd, 'read_sql', _fake_read_sql)
    return seen


# 07G07 실측 기준가 (dt.DWPM10510 MOD_STPR, 2026-06~07).
# 6/29 행이 있어야 구코드(start_dt-1)가 실제로 다른 값을 내고 테스트가 걸린다.
_PRICES = pd.DataFrame([
    {'FUND_CD': '07G02', 'STD_DT': '20260629', 'MOD_STPR': 1274.476433},
    {'FUND_CD': '07G02', 'STD_DT': '20260630', 'MOD_STPR': 1281.512708},
    {'FUND_CD': '07G02', 'STD_DT': '20260731', 'MOD_STPR': 1205.402447},
    {'FUND_CD': '07G03', 'STD_DT': '20260629', 'MOD_STPR': 1643.818715},
    {'FUND_CD': '07G03', 'STD_DT': '20260630', 'MOD_STPR': 1658.164108},
    {'FUND_CD': '07G03', 'STD_DT': '20260731', 'MOD_STPR': 1515.611025},
])


def test_base_is_period_start_not_the_day_before(monkeypatch):
    """분모는 **기초일(전월말) 종가** — 하루 더 빼면 off-by-one 이다."""
    seen = _patch_db(monkeypatch, _PRICES)
    svc._sub_portfolio_returns('07G07', datetime(2026, 6, 30), datetime(2026, 7, 31))
    assert seen['params'] == ['20260630', '20260731']
    assert '20260629' not in seen['params']


def test_returns_match_pa_window(monkeypatch):
    """6/30 종가 기준 = PA·기준가와 같은 값 (6/29 기준이면 -5.42/-7.80 이 나온다)."""
    _patch_db(monkeypatch, _PRICES)
    out = svc._sub_portfolio_returns('07G07', datetime(2026, 6, 30), datetime(2026, 7, 31))
    assert round(out['인컴추구'], 2) == -5.94
    assert round(out['수익추구'], 2) == -8.60


def test_none_when_fund_has_no_sub_portfolios(monkeypatch):
    _patch_db(monkeypatch, _PRICES)
    assert svc._sub_portfolio_returns('08K88', datetime(2026, 6, 30),
                                      datetime(2026, 7, 31)) is None


def test_adapter_fund_return_is_a_float_not_a_dict():
    """호출부가 dict 로 다루면 07G07 처럼 죽는다 — 계약을 테스트로 고정한다."""
    pa_result = {'asset_summary': pd.DataFrame([
        {'자산군': '포트폴리오', '개별수익률': -0.073413, '기여수익률': None,
         '순자산비중_끝': None},
        {'자산군': '국내주식', '개별수익률': -0.19, '기여수익률': -0.0405,
         '순자산비중_끝': 21.39},
    ])}
    out = svc._adapt_compute_single_port_pa(pa_result)
    assert isinstance(out['fund_return'], float)
    assert out['fund_return'] == -7.3413
    assert not hasattr(out['fund_return'], 'get')
