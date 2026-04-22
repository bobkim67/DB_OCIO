from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from ..schemas.holdings import HoldingsResponseDTO
from ..services.holdings_service import build_holdings

router = APIRouter()


@router.get(
    "/funds/{code}/holdings",
    response_model=HoldingsResponseDTO,
)
def get_holdings(
    code: str,
    lookthrough: bool = Query(default=False),
    as_of_date: str | None = Query(default=None),
) -> HoldingsResponseDTO:
    if as_of_date is not None:
        try:
            datetime.strptime(as_of_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_PARAM",
                    "message": "as_of_date must be YYYY-MM-DD",
                },
            )
    try:
        return build_holdings(
            fund_code=code,
            lookthrough=lookthrough,
            as_of_date=as_of_date,
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": code},
        )
