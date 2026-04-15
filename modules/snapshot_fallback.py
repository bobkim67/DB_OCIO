# -*- coding: utf-8 -*-
"""DB 접속 실패 시 JSON snapshot에서 데이터를 반환하는 fallback 모듈.

Streamlit Cloud 등 내부 DB 접근 불가 환경에서 사용.
data/mock_snapshots/{fund_code}_{date}.json 파일을 읽어
data_loader와 동일한 형태의 DataFrame/dict를 반환.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

_SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / 'data' / 'mock_snapshots'
_CACHE: dict = {}


def _load_snapshot(fund_code: str) -> dict | None:
    """가장 최근 snapshot JSON 로드."""
    if fund_code in _CACHE:
        return _CACHE[fund_code]
    files = sorted(_SNAPSHOT_DIR.glob(f'{fund_code}_*.json'), reverse=True)
    if not files:
        return None
    data = json.loads(files[0].read_text(encoding='utf-8'))
    _CACHE[fund_code] = data
    return data


def has_snapshot(fund_code: str) -> bool:
    return _load_snapshot(fund_code) is not None


def load_nav_fallback(fund_code: str, start_date=None) -> pd.DataFrame:
    """NAV 시계열 — load_fund_nav_with_aum 대체."""
    snap = _load_snapshot(fund_code)
    if not snap:
        return pd.DataFrame()
    rows = snap['nav_series']
    df = pd.DataFrame(rows)
    df['기준일자'] = pd.to_datetime(df['date'].astype(str), format='%Y%m%d')
    df['MOD_STPR'] = df['nav']
    df['AUM_억'] = df['aum']
    df['DD1_ERN_RT'] = df['daily_return']
    df['FUND_CD'] = fund_code
    if start_date:
        sd = pd.Timestamp(str(start_date)[:4] + '-' + str(start_date)[4:6] + '-' + str(start_date)[6:8])
        df = df[df['기준일자'] >= sd]
    return df.sort_values('기준일자').reset_index(drop=True)


def load_holdings_fallback(fund_code: str) -> pd.DataFrame:
    """보유종목 — load_fund_holdings_classified 대체."""
    from modules.data_loader import _classify_6class
    snap = _load_snapshot(fund_code)
    if not snap:
        return pd.DataFrame()
    rows = snap['holdings']
    df = pd.DataFrame(rows)
    df['ITEM_CD'] = df['item_cd']
    df['ITEM_NM'] = df['item_nm']
    df['비중(%)'] = df['weight']
    df['평가금액(억)'] = df['evl_amt']
    df['AST_CLSF_CD_NM'] = df['ast_clsf']
    df['CURR_DS_CD'] = df['curr']
    df['기준일자'] = pd.Timestamp(str(snap['snapshot_date']), tz=None)
    df['자산군'] = df.apply(_classify_6class, axis=1)
    return df


def load_pa_fallback(fund_code: str) -> dict | None:
    """PA 기여도 — compute_single_port_pa 대체."""
    snap = _load_snapshot(fund_code)
    if not snap or not snap.get('pa_attribution'):
        return None
    pa = snap['pa_attribution']
    asset_summary = pd.DataFrame(pa)
    asset_summary = asset_summary.rename(columns={
        'class': '자산군', 'weight': '순자산비중', 'return': '개별수익률', 'contrib': '기여수익률'
    })
    # % → 비율로 변환 (data_loader 출력과 일치)
    asset_summary['순자산비중'] = asset_summary['순자산비중'] / 100
    asset_summary['개별수익률'] = asset_summary['개별수익률'] / 100
    asset_summary['기여수익률'] = asset_summary['기여수익률'] / 100
    return {
        'asset_summary': asset_summary,
        'sec_summary': pd.DataFrame(),  # 종목 상세는 없음
        'asset_daily': pd.DataFrame(),
        'sec_daily': pd.DataFrame(),
    }


def load_trades_fallback(fund_code: str) -> dict:
    """거래내역 — load_fund_net_trades 대체."""
    snap = _load_snapshot(fund_code)
    if not snap:
        return {}
    return snap.get('trades', {})


def load_bm_fallback(fund_code: str) -> tuple:
    """BM 시계열 — 빈 반환 (BM 미설정 처리)."""
    return None, None
