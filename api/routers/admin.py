from fastapi import APIRouter, Query

from ..schemas.admin import (
    AdminDebatePeriodsResponseDTO,
    AdminDebateStatusResponseDTO,
    AdminEvidenceQualityResponseDTO,
    AdminReportEnrichmentResponseDTO,
)
from ..services.admin_service import (
    build_debate_periods,
    build_debate_status,
    build_evidence_quality,
    build_report_enrichment_diagnosis,
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


@router.get(
    "/admin/report-enrichment",
    response_model=AdminReportEnrichmentResponseDTO,
    tags=["admin"],
    summary="Admin/debug enrichment 진단 (read-only)",
    description=(
        "관리자/개발자 진단용 read-only endpoint. "
        "client endpoint(`/api/market-report`, `/api/funds/{fund}/report`) 와 달리 "
        "approved=false 인 final 도 `final_unapproved` 상태로 노출하며, "
        "InternalReportEnrichmentDTO (internal_source + raw reason 포함) 와 "
        "debate_run_id / approved_debate_run_id / draft_run_id 를 노출한다. "
        "이 endpoint 는 인증 없는 환경에서는 보안 경계가 아니다 — "
        "외부 노출 운영환경에서는 인증/권한 가드를 별도로 적용해야 한다."
    ),
)
def get_report_enrichment_diagnosis(
    period: str = Query(..., pattern=r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$"),
    fund: str = Query(..., min_length=1, max_length=32),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> AdminReportEnrichmentResponseDTO:
    return build_report_enrichment_diagnosis(
        period=period, fund_code=fund, limit=limit,
    )
