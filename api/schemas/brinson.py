"""Brinson 3-Factor Attribution DTO.

`modules.data_loader.compute_brinson_attribution_v2` 반환을 Pydantic 으로 정규화.

단위 규약:
  - 비중 (AP비중/BM비중): % (예: 25.3 → 25.3%) — Streamlit 화면 그대로.
  - 수익률·기여도·factor effect: % (예: 1.23 → 1.23%) — Streamlit `pa_df` 컬럼 단위.
  - daily_brinson 누적: % (이미 ×100 적용됨, raw cum*100).
  - sec_contrib 의 수익률(%)/기여수익률(%): %.

Streamlit `tabs/brinson.py` 와 단위 일관 (raw ratio 가 아님). 클라이언트에서 추가 변환 불필요.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from .meta import BaseMeta


class BrinsonAssetRowDTO(BaseModel):
    """compute_brinson_attribution_v2['pa_df'] 한 행."""
    asset_class: str           # 자산군 (예: "국내주식")
    ap_weight: float           # AP비중 (%)
    bm_weight: float           # BM비중 (%)
    ap_return: float           # AP수익률 (%)
    bm_return: float           # BM수익률 (%)
    alloc_effect: float        # Allocation Effect (%)
    select_effect: float       # Selection Effect (%)
    cross_effect: float        # Cross Effect (%)
    contrib_return: float      # 기여수익률 (%)


class BrinsonSecContribDTO(BaseModel):
    """compute_brinson_attribution_v2['sec_contrib'] 한 행 (전체 종목)."""
    asset_class: str           # 자산군
    item_nm: str               # 종목명
    weight_pct: float          # 비중(%)
    return_pct: float          # 수익률(%)
    contrib_pct: float         # 기여수익률(%)


class BrinsonDailyPointDTO(BaseModel):
    """compute_brinson_attribution_v2['daily_brinson'] 한 행."""
    date: date                 # 기준일자
    alloc_cum: float           # 누적 Allocation (%)
    select_cum: float          # 누적 Selection (%)
    cross_cum: float           # 누적 Cross (%)
    excess_cum: float          # 누적 초과수익 (%)


class BrinsonResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    start_date: date
    end_date: date
    mapping_method: str        # "방법1"|"방법2"|"방법3"|"방법4"
    pa_method: str             # "8"|"5"
    fx_split: bool             # FX 분리 토글 echo
    # 합계 (모두 %)
    period_ap_return: float
    period_bm_return: float
    total_alloc: float
    total_select: float
    total_cross: float
    total_excess: float
    total_excess_relative: float
    fx_contrib: float
    residual: float
    # 자산군별
    asset_rows: list[BrinsonAssetRowDTO]
    # 종목별 기여 (top 20)
    sec_contrib: list[BrinsonSecContribDTO]
    # 일별 누적 Brinson (수익률 비교 차트용)
    daily_brinson: list[BrinsonDailyPointDTO]
