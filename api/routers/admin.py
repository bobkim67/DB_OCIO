from fastapi import APIRouter, Query

from ..schemas.admin import (
    AdminDebatePeriodsResponseDTO,
    AdminDebateStatusResponseDTO,
    AdminEvidenceQualityResponseDTO,
)
from ..services.admin_service import (
    build_debate_periods,
    build_debate_status,
    build_evidence_quality,
)

router = APIRouter()


@router.get(
    "/admin/evidence-quality",
    response_model=AdminEvidenceQualityResponseDTO,
)
def get_evidence_quality(
    limit: int | None = Query(default=None, ge=1, le=500),
    fund_code: str | None = Query(default=None),
) -> AdminEvidenceQualityResponseDTO:
    fc = fund_code.strip() if fund_code else None
    if fc == "":
        fc = None
    return build_evidence_quality(limit=limit, fund_code=fc)


@router.get(
    "/admin/debate-status",
    response_model=AdminDebateStatusResponseDTO,
)
def get_debate_status(
    period: str = Query(..., pattern=r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$"),
    fund: str = Query(..., min_length=1, max_length=32),
) -> AdminDebateStatusResponseDTO:
    return build_debate_status(period=period, fund_code=fund)


@router.get(
    "/admin/debate-periods",
    response_model=AdminDebatePeriodsResponseDTO,
)
def get_debate_periods() -> AdminDebatePeriodsResponseDTO:
    return build_debate_periods()
