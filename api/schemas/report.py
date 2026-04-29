from datetime import datetime

from pydantic import BaseModel

from .meta import BaseMeta


class ReportFinalDTO(BaseModel):
    """report_output/{period}/{fund}.final.json 의 client-노출 필드.

    실파일 필드 (2026-04-29 조사):
      approved, approved_at, approved_by, consensus_points, tail_risks,
      cost_usd, final_comment, fund_code, generated_at, model, period, status

    Client에 미노출:
      - cost_usd (운영원가)
      - status (approved 필터링 후 의미 없음)

    빈 list 가능: consensus_points / tail_risks (펀드 코멘트는 보통 비어 있음).
    """
    period: str
    fund_code: str
    final_comment: str
    generated_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    model: str | None = None
    consensus_points: list[str] = []
    tail_risks: list[str] = []


class ReportFinalResponseDTO(BaseModel):
    meta: BaseMeta
    data: ReportFinalDTO


class ReportApprovedPeriodsResponseDTO(BaseModel):
    """approved=true 인 final.json 이 존재하는 기간 목록 (정렬: 내림차순)."""
    meta: BaseMeta
    fund_code: str  # 시장 코멘트는 "_market"
    periods: list[str]
