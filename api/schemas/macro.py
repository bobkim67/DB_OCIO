from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from .meta import BaseMeta


class MacroPointDTO(BaseModel):
    date_: date = Field(alias="date")
    value: float

    model_config = {"populate_by_name": True}


class MacroSeriesDTO(BaseModel):
    key: str                         # public key (PE/EPS/USDKRW 또는 내부 키)
    label: str
    unit: Literal["pct", "bp", "idx", "ratio", "krw", "usd", "raw"] = "raw"
    points: list[MacroPointDTO]


class MacroTimeseriesResponseDTO(BaseModel):
    meta: BaseMeta
    series: list[MacroSeriesDTO]
