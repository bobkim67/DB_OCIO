"""GET /api/funds/{code}/brinson — Brinson 3-Factor Attribution.

Query params:
  start_date / end_date  : YYYY-MM-DD (선택, 미지정 시 YTD 또는 inception)
  mapping_method         : 방법1|방법2|방법3|방법4 (선택, 펀드별 기본값)
  pa_method              : 8|5 (선택, 기본 8)
  fx_split               : true|false (선택, 기본 true)
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query

from ..schemas.brinson import BrinsonResponseDTO
from ..services.brinson_service import (
    ALLOWED_MAPPING_METHODS,
    ALLOWED_PA_METHODS,
    build_brinson,
)

router = APIRouter()


def _parse_iso(name: str, value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PARAM",
                    "message": f"{name} must be YYYY-MM-DD"},
        )


@router.get(
    "/funds/{code}/brinson",
    response_model=BrinsonResponseDTO,
)
def get_brinson(
    code: str,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    mapping_method: str | None = Query(default=None),
    pa_method: str = Query(default="8"),
    fx_split: bool = Query(default=True),
) -> BrinsonResponseDTO:
    sd = _parse_iso("start_date", start_date)
    ed = _parse_iso("end_date", end_date)
    if mapping_method is not None and mapping_method not in ALLOWED_MAPPING_METHODS:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PARAM",
                    "message": f"mapping_method must be one of {list(ALLOWED_MAPPING_METHODS)}"},
        )
    if pa_method not in ALLOWED_PA_METHODS:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PARAM",
                    "message": f"pa_method must be one of {list(ALLOWED_PA_METHODS)}"},
        )
    try:
        return build_brinson(
            code,
            start_date=sd, end_date=ed,
            mapping_method=mapping_method,
            pa_method=pa_method,
            fx_split=fx_split,
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": code},
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PARAM", "message": str(exc)},
        )
