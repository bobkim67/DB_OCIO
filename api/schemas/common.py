from pydantic import BaseModel

from .fund import FundMetaDTO
from .meta import BaseMeta


class ErrorDTO(BaseModel):
    code: str                # "FUND_NOT_FOUND", "INVALID_PARAM", "CONFIG_MISSING"
    message: str
    detail: dict | None = None


class FundListResponseDTO(BaseModel):
    """GET /api/funds — 구체 alias (Envelope Generic 회피)."""
    meta: BaseMeta
    data: list[FundMetaDTO]
