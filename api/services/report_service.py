"""Approved final.json 뷰어 서비스.

- 시장 코멘트 (`_market`): 펀드와 독립된 매크로 산출물
- 펀드 코멘트: 시장 코멘트 + 거래/편입 기반으로 작성된 fund-scoped 산출물

규약:
  - approved=true 인 final.json 만 client에 노출 (404 처리)
  - 읽기 전용. report_store.save_* 계열 절대 호출 금지
  - fund_code 화이트리스트: 9 운용 펀드. 시장 라우터는 `_market` 고정
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException

from ..schemas.meta import BaseMeta, SourceBreakdown
from ..schemas.report import (
    ReportApprovedPeriodsResponseDTO,
    ReportFinalDTO,
    ReportFinalResponseDTO,
)
from . import report_store_gateway as rsg


# 펀드 코멘트 화이트리스트 (시장 `_market` 별도 라우터)
ALLOWED_REPORT_FUNDS: frozenset[str] = frozenset({
    "07G02", "07G03", "07G04",
    "08K88", "08N33", "08N81",
    "08P22", "2JM23", "4JM12",
})

_MARKET_FUND_CODE = "_market"
_FUND_SAFE_RE = re.compile(r"^[A-Za-z0-9_]+$")


# ──────────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────────

def _validate_period(period: str) -> str:
    p = (period or "").strip()
    if not rsg.is_valid_period(p):
        raise HTTPException(status_code=422, detail="invalid period format")
    return p


def _validate_fund(fund_code: str) -> str:
    fc = (fund_code or "").strip()
    if not fc or not _FUND_SAFE_RE.match(fc):
        raise HTTPException(status_code=422, detail="invalid fund format")
    if fc not in ALLOWED_REPORT_FUNDS:
        raise HTTPException(status_code=422, detail="fund not in whitelist")
    return fc


# ──────────────────────────────────────────────────────────────────────────
# DTO assembly
# ──────────────────────────────────────────────────────────────────────────

def _to_dto(payload: dict, period: str, fund_code: str) -> ReportFinalDTO:
    """final.json dict → DTO. payload는 approved=true 검증을 마쳤다고 가정."""
    cp = payload.get("consensus_points") or []
    tr = payload.get("tail_risks") or []
    # str로 변환 (혹시 dict 등이 섞여 들어온 경우 안전하게 처리)
    cp = [str(x) for x in cp if x is not None]
    tr = [str(x) for x in tr if x is not None]
    return ReportFinalDTO(
        period=payload.get("period") or period,
        fund_code=payload.get("fund_code") or fund_code,
        final_comment=str(payload.get("final_comment") or ""),
        generated_at=payload.get("generated_at"),
        approved_at=payload.get("approved_at"),
        approved_by=payload.get("approved_by"),
        model=payload.get("model"),
        consensus_points=cp,
        tail_risks=tr,
    )


def _make_meta(approved_at: datetime | None) -> BaseMeta:
    as_of = None
    if isinstance(approved_at, datetime):
        as_of = approved_at.date()
    elif isinstance(approved_at, str):
        try:
            as_of = datetime.fromisoformat(approved_at).date()
        except ValueError:
            as_of = None
    return BaseMeta(
        as_of_date=as_of,
        source="db",
        sources=[SourceBreakdown(component="report_store", kind="db")],
        is_fallback=False,
        warnings=[],
        generated_at=datetime.now(timezone.utc),
    )


# ──────────────────────────────────────────────────────────────────────────
# Build entry points
# ──────────────────────────────────────────────────────────────────────────

def _build_report(period: str, fund_code: str) -> ReportFinalResponseDTO:
    """공통 빌더: load_final → approved 검증 → DTO."""
    payload = rsg.load_final(period, fund_code)
    if not payload:
        raise HTTPException(
            status_code=404,
            detail={"code": "REPORT_NOT_FOUND",
                    "message": f"{fund_code}@{period}"},
        )
    if not payload.get("approved"):
        # final.json은 있으나 approved=false → 미노출
        raise HTTPException(
            status_code=404,
            detail={"code": "REPORT_NOT_APPROVED",
                    "message": f"{fund_code}@{period}"},
        )

    dto = _to_dto(payload, period, fund_code)
    return ReportFinalResponseDTO(
        meta=_make_meta(payload.get("approved_at")),
        data=dto,
    )


def build_market_report(period: str) -> ReportFinalResponseDTO:
    p = _validate_period(period)
    return _build_report(p, _MARKET_FUND_CODE)


def build_fund_report(period: str, fund_code: str) -> ReportFinalResponseDTO:
    p = _validate_period(period)
    fc = _validate_fund(fund_code)
    return _build_report(p, fc)


# ──────────────────────────────────────────────────────────────────────────
# Approved periods listing
# ──────────────────────────────────────────────────────────────────────────

def _list_approved_periods(fund_code: str) -> list[str]:
    """fund_code(_market 포함)의 approved=true final.json 이 존재하는 기간 목록.

    report_store.list_period_dirs() 로 모든 기간 디렉터리를 스캔 후,
    각 기간에서 load_final → approved=true 인 것만 추림.
    정렬: 내림차순 (rsg.list_period_dirs 가 이미 desc 반환).
    """
    out: list[str] = []
    for period in rsg.list_period_dirs():
        payload = rsg.load_final(period, fund_code)
        if payload and payload.get("approved"):
            out.append(period)
    return out


def build_market_approved_periods() -> ReportApprovedPeriodsResponseDTO:
    periods = _list_approved_periods(_MARKET_FUND_CODE)
    return ReportApprovedPeriodsResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source="db",
            sources=[SourceBreakdown(component="report_store", kind="db")],
            is_fallback=False,
            warnings=[],
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=_MARKET_FUND_CODE,
        periods=periods,
    )


def build_fund_approved_periods(fund_code: str) -> ReportApprovedPeriodsResponseDTO:
    fc = _validate_fund(fund_code)
    periods = _list_approved_periods(fc)
    return ReportApprovedPeriodsResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source="db",
            sources=[SourceBreakdown(component="report_store", kind="db")],
            is_fallback=False,
            warnings=[],
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fc,
        periods=periods,
    )
