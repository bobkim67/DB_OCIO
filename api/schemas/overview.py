from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .meta import BaseMeta


class NavPointDTO(BaseModel):
    date_: date = Field(alias="date")
    nav: float
    bm: float | None = None
    excess: float | None = None
    aum: float | None = None

    model_config = {"populate_by_name": True}


class MetricCardDTO(BaseModel):
    key: str
    label: str
    value: float                    # raw ratio (0.0123 = 1.23%)
    unit: Literal["pct", "bp", "currency", "raw"] = "pct"
    bm_value: float | None = None
    excess_value: float | None = None


class OverviewResponseDTO(BaseModel):
    meta: BaseMeta
    fund_code: str
    fund_name: str
    inception_date: date
    bm_configured: bool
    cards: list[MetricCardDTO]       # Week 1: 1개 ("설정후")
    nav_series: list[NavPointDTO]    # Week 1: nav/aum만. bm/excess는 항상 None
