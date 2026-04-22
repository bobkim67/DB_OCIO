from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

SourceKind = Literal["db", "cache", "mock", "mixed"]
ComponentSourceKind = Literal["db", "cache", "mock"]


class SourceBreakdown(BaseModel):
    component: str
    kind: ComponentSourceKind
    note: str | None = None


class BaseMeta(BaseModel):
    as_of_date: date | None = None
    source: SourceKind = "db"
    sources: list[SourceBreakdown] = Field(default_factory=list)
    is_fallback: bool = False
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime
