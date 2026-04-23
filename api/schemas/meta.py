from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

SourceKind = Literal["db", "cache", "mock", "mixed"]
ComponentSourceKind = Literal["db", "cache", "mock"]


class SourceBreakdown(BaseModel):
    component: str
    kind: ComponentSourceKind
    note: str | None = None


class BaseMeta(BaseModel):
    # sources/warnings는 always-present (empty list라도). openapi-typescript 생성물이
    # 이들을 non-optional로 잡도록 default 제거하고 required 필드로 둠.
    # 모든 서비스 호출부가 sources=[...], warnings=[...]를 명시 전달 중.
    as_of_date: date | None = None
    source: SourceKind = "db"
    sources: list[SourceBreakdown]
    is_fallback: bool = False
    warnings: list[str]
    generated_at: datetime
