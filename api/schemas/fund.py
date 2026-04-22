from datetime import date

from pydantic import BaseModel


class FundMetaDTO(BaseModel):
    code: str
    name: str
    group: str
    inception: date
    bm_configured: bool
    default_mapping_method: str
    # aum 필드 없음 — 목록 조회에서 9펀드 NAV 로딩(N+1) 방지.
    # AUM은 /funds/{code}/overview의 nav_series[].aum에서 제공.
