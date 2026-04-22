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
