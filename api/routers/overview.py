from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from ..schemas.overview import OverviewResponseDTO, PeriodReturnsResponseDTO
from ..services.overview_service import build_overview, build_period_returns

router = APIRouter()


@router.get("/funds/{code}/overview", response_model=OverviewResponseDTO)
def get_overview(
    code: str,
    start_date: str | None = Query(default=None),
) -> OverviewResponseDTO:
    if start_date is not None:
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_PARAM",
                    "message": "start_date must be YYYY-MM-DD",
                },
            )
    try:
        return build_overview(fund_code=code, start_date=start_date)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": code},
        )


@router.get(
    "/funds/{code}/period-returns", response_model=PeriodReturnsResponseDTO,
)
def get_period_returns(
    code: str,
    end_date: str | None = Query(default=None),
) -> PeriodReturnsResponseDTO:
    """조회 종료일(end_date, YYYY-MM-DD) 앵커 기간별 수익률 — Overview/성과분석 표용."""
    if end_date is not None:
        try:
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_PARAM",
                    "message": "end_date must be YYYY-MM-DD",
                },
            )
    try:
        return build_period_returns(code, end_date)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": code},
        )
