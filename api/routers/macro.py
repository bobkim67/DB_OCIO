from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from ..schemas.macro import MacroTimeseriesResponseDTO
from ..services.macro_service import (
    _normalize_keys,
    build_macro_timeseries,
)

router = APIRouter()


@router.get(
    "/macro/timeseries",
    response_model=MacroTimeseriesResponseDTO,
)
def get_macro_timeseries(
    keys: list[str] | None = Query(default=None),
    start: str | None = Query(default=None),
) -> MacroTimeseriesResponseDTO:
    if start is not None:
        try:
            datetime.strptime(start, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_PARAM",
                    "message": "start must be YYYY-MM-DD",
                },
            )
    if keys is not None:
        normalized = _normalize_keys(keys)
        if len(normalized) == 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "INVALID_PARAM",
                    "message": "keys must be non-empty",
                },
            )
    return build_macro_timeseries(keys=keys, start_date=start)
