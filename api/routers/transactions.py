from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from ..schemas.transactions import (
    FxPositionResponseDTO,
    SecuritiesResponseDTO,
    SecurityReturnResponseDTO,
    TransactionsResponseDTO,
    WeightHistoryResponseDTO,
)
from ..services.transactions_service import (
    build_asset_class_return,
    build_fx_position,
    build_securities,
    build_security_return,
    build_transactions,
    build_weight_history,
)

router = APIRouter()


def _validate_date(name: str, value: str) -> None:
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PARAM", "message": f"{name} must be YYYY-MM-DD"},
        )


@router.get(
    "/funds/{code}/transactions",
    response_model=TransactionsResponseDTO,
)
def get_transactions(
    code: str,
    start: str = Query(..., description="조회 시작일 YYYY-MM-DD"),
    end: str = Query(..., description="조회 종료일 YYYY-MM-DD"),
) -> TransactionsResponseDTO:
    _validate_date("start", start)
    _validate_date("end", end)
    try:
        return build_transactions(fund_code=code, start_date=start, end_date=end)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": code},
        )


@router.get(
    "/funds/{code}/weight-history",
    response_model=WeightHistoryResponseDTO,
)
def get_weight_history(
    code: str,
    start: str = Query(..., description="조회 시작일 YYYY-MM-DD"),
    level: str = Query("security", description="security | asset"),
) -> WeightHistoryResponseDTO:
    _validate_date("start", start)
    if level not in ("security", "asset"):
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PARAM", "message": "level must be security|asset"},
        )
    try:
        return build_weight_history(fund_code=code, start_date=start, level=level)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "FUND_NOT_FOUND", "message": code},
        )


@router.get(
    "/funds/{code}/fx-position",
    response_model=FxPositionResponseDTO,
)
def get_fx_position(
    code: str,
    start: str = Query(..., description="조회 시작일 YYYY-MM-DD"),
) -> FxPositionResponseDTO:
    _validate_date("start", start)
    try:
        return build_fx_position(fund_code=code, start_date=start)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "FUND_NOT_FOUND", "message": code})


@router.get(
    "/funds/{code}/securities",
    response_model=SecuritiesResponseDTO,
)
def get_securities(
    code: str,
    start: str | None = Query(None, description="편입이력 조회 시작일 YYYY-MM-DD (지정 시 현재 미보유 종목 하단 포함)"),
) -> SecuritiesResponseDTO:
    if start:
        _validate_date("start", start)
    try:
        return build_securities(fund_code=code, start_date=start)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "FUND_NOT_FOUND", "message": code})


@router.get(
    "/funds/{code}/security-returns",
    response_model=SecurityReturnResponseDTO,
)
def get_security_returns(
    code: str,
    item_cd: str = Query(..., description="종목코드(ISIN)"),
    item_nm: str = Query("", description="종목명(표시용)"),
    start: str = Query(..., description="조회 시작일 YYYY-MM-DD"),
    end: str = Query(..., description="조회 종료일 YYYY-MM-DD"),
) -> SecurityReturnResponseDTO:
    _validate_date("start", start)
    _validate_date("end", end)
    try:
        return build_security_return(
            fund_code=code, item_cd=item_cd, item_nm=item_nm,
            start_date=start, end_date=end,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "FUND_NOT_FOUND", "message": code})


@router.get(
    "/funds/{code}/asset-class-return",
    response_model=SecurityReturnResponseDTO,
)
def get_asset_class_return(
    code: str,
    asset_class: str = Query(..., description="자산군(6버킷: 국내주식~금/대체)"),
    start: str = Query(..., description="조회 시작일 YYYY-MM-DD"),
    end: str = Query(..., description="조회 종료일 YYYY-MM-DD"),
) -> SecurityReturnResponseDTO:
    _validate_date("start", start)
    _validate_date("end", end)
    try:
        return build_asset_class_return(
            fund_code=code, asset_class=asset_class,
            start_date=start, end_date=end,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "FUND_NOT_FOUND", "message": code})
