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


# ──────────────────────────────────────────────────────────────────
# R3-c: Wiki coverage report endpoints (read-only)
# ──────────────────────────────────────────────────────────────────

from fastapi import HTTPException, Path as FastAPIPath
from ..schemas.meta import BaseMeta
from ..schemas.wiki_coverage import (
    WikiCoverageReportListItemDTO,
    WikiCoverageReportListResponseDTO,
    WikiCoverageReportFullResponseDTO,
)
from ..services import wiki_coverage_gateway as _wcg


def _wc_meta() -> BaseMeta:
    return BaseMeta(sources=[], warnings=[])


@router.get(
    "/admin/wiki-coverage/reports",
    response_model=WikiCoverageReportListResponseDTO,
    tags=["admin"],
    summary="Wiki coverage report 목록 (R3, read-only)",
)
def list_wiki_coverage_reports() -> WikiCoverageReportListResponseDTO:
    raw = _wcg.list_reports()
    items = [
        WikiCoverageReportListItemDTO(
            id=r["id"],
            generated_at=r.get("generated_at"),
            periods=r.get("periods", []),
            funds=r.get("funds", []),
            gate_summary=r.get("gate_summary", {}),
            size_bytes=r.get("size_bytes", 0),
        )
        for r in raw
    ]
    return WikiCoverageReportListResponseDTO(meta=_wc_meta(), reports=items)


@router.get(
    "/admin/wiki-coverage/latest",
    response_model=WikiCoverageReportFullResponseDTO,
    tags=["admin"],
    summary="가장 최근 wiki coverage report (R3)",
)
def get_latest_wiki_coverage() -> WikiCoverageReportFullResponseDTO:
    payload = _wcg.load_latest_report()
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "WIKI_COVERAGE_NO_REPORTS",
                     "message": "no wiki coverage reports found"},
        )
    items = _wcg.list_reports()
    rid = items[0]["id"] if items else "unknown"
    return WikiCoverageReportFullResponseDTO(
        meta=_wc_meta(), report_id=rid, payload=payload,
    )


@router.get(
    "/admin/wiki-coverage/{report_id}",
    response_model=WikiCoverageReportFullResponseDTO,
    tags=["admin"],
    summary="특정 wiki coverage report (R3)",
)
def get_wiki_coverage_report(
    report_id: str = FastAPIPath(..., pattern=r"^[A-Za-z0-9_\-]+$",
                                  min_length=1, max_length=128),
) -> WikiCoverageReportFullResponseDTO:
    try:
        payload = _wcg.load_report(report_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "WIKI_COVERAGE_INVALID_ID", "message": str(exc)},
        )
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "WIKI_COVERAGE_NOT_FOUND",
                     "message": f"report {report_id!r} not found"},
        )
    return WikiCoverageReportFullResponseDTO(
        meta=_wc_meta(), report_id=report_id, payload=payload,
    )
