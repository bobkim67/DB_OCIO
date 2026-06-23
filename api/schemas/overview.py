from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .meta import BaseMeta


class NavPointDTO(BaseModel):
    date_: date = Field(alias="date")
    nav: float
    bm: float | None = None         # Week 2: BM rebased to NAV first value
    excess: float | None = None     # Week 2: (nav/nav[0]) - (bm/bm[0]), raw ratio
    aum: float | None = None

    model_config = {"populate_by_name": True}


class MetricCardDTO(BaseModel):
    key: str                        # "since_inception" | "ytd" | "mdd" | "vol"
    label: str
    value: float                    # raw ratio (0.0123 = 1.23%)
    unit: Literal["pct", "bp", "currency", "raw"] = "pct"
    bm_value: float | None = None
    excess_value: float | None = None


PeriodReturnsDTO = dict[str, float]
# keys: "1M" | "3M" | "6M" | "YTD" | "1Y" | "SI"
# value: raw ratio. 누락 기간은 dict에 key 미포함으로 표현.


class FundInfoDTO(BaseModel):
    """펀드 기본정보(Overview 메타바). OCIO 사모라 거래소 티커 대신 KSD 표준코드."""
    ticker: str | None = None        # KSD 표준코드 (거래소 티커 없음 — 사모)
    inception: date | None = None    # 설정일 (DWPI10011.FRST_OPNG_DT)
    setup_amount: float | None = None  # 설정액 = 최신 순자산(NAST_AMT), 원
    fund_type: str | None = None     # 펀드타입 (사모 · 수익증권 등)
    manager: str | None = None       # 운용사
    fee_bp: float | None = None      # 총보수율 (bp, BOS3203 컴포넌트 합)
    nav: float | None = None         # 최신 기준가 (MOD_STPR)


class OverviewResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    inception_date: date
    bm_configured: bool
    cards: list[MetricCardDTO]                # Week 2: 최대 4개
    nav_series: list[NavPointDTO]             # Week 2: bm/excess 채움(가능 시)
    period_returns: PeriodReturnsDTO = Field(default_factory=dict)
    bm_period_returns: PeriodReturnsDTO = Field(default_factory=dict)
    fund_meta: FundInfoDTO | None = None      # 펀드 기본정보 (ticker/설정일/설정액/타입/운용사/보수/NAV)
