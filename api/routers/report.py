"""Approved final.json 뷰어 라우터 (Client-facing).

URL 분리:
  - 시장 코멘트 (펀드 독립):  /api/market-report
  - 펀드 코멘트 (fund-scoped): /api/funds/{fund}/report

W7 admin 라우터(/api/admin/debate-status, debate-periods)는 검수용으로
fund 파라미터에 `_market`을 끼워넣는 절충을 채택했지만, client viewer는
시장/펀드가 의미적으로 다른 산출물이므로 URL을 분리한다.
"""
from fastapi import APIRouter, Path, Query

from ..schemas.report import (
    ReportApprovedPeriodsResponseDTO,
    ReportFinalResponseDTO,
)
from ..services.report_service import (
    build_fund_approved_periods,
    build_fund_report,
    build_market_approved_periods,
    build_market_report,
)

router = APIRouter()


# ──────────── 시장 ────────────

@router.get(
    "/market-report",
    response_model=ReportFinalResponseDTO,
)
def get_market_report(
    period: str = Query(..., pattern=r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$"),
) -> ReportFinalResponseDTO:
    return build_market_report(period=period)


@router.get(
    "/market-report/approved-periods",
    response_model=ReportApprovedPeriodsResponseDTO,
)
def list_market_approved_periods() -> ReportApprovedPeriodsResponseDTO:
    return build_market_approved_periods()


# ──────────── 펀드 ────────────

@router.get(
    "/funds/{fund}/report",
    response_model=ReportFinalResponseDTO,
)
def get_fund_report(
    fund: str = Path(..., min_length=1, max_length=32),
    period: str = Query(..., pattern=r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$"),
) -> ReportFinalResponseDTO:
    return build_fund_report(period=period, fund_code=fund)


@router.get(
    "/funds/{fund}/report/approved-periods",
    response_model=ReportApprovedPeriodsResponseDTO,
)
def list_fund_approved_periods(
    fund: str = Path(..., min_length=1, max_length=32),
) -> ReportApprovedPeriodsResponseDTO:
    return build_fund_approved_periods(fund_code=fund)
