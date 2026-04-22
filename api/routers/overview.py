from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from ..schemas.overview import OverviewResponseDTO
from ..services.overview_service import build_overview

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
