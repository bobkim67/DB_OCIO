from datetime import datetime, timezone

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
    return BaseMeta(sources=[], warnings=[],
                    generated_at=datetime.now(timezone.utc))


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


# ──────────────────────────────────────────────────────────────────
# R4: Comment trace endpoints (read-only)
# ──────────────────────────────────────────────────────────────────

from ..schemas.comment_trace import (
    CommentTraceListItemDTO,
    CommentTraceListResponseDTO,
    CommentTraceFullResponseDTO,
)
from ..services import comment_trace_gateway as _ctg


@router.get(
    "/admin/comment-trace",
    response_model=CommentTraceListResponseDTO,
    tags=["admin"],
    summary="Comment trace 목록 (R4, read-only)",
)
def list_comment_traces(
    period: str | None = Query(default=None,
                                pattern=r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$"),
    fund: str | None = Query(default=None, min_length=1, max_length=32,
                              pattern=r"^[A-Za-z0-9_]+$"),
) -> CommentTraceListResponseDTO:
    raw = _ctg.list_traces(period=period, fund=fund)
    items = [
        CommentTraceListItemDTO(
            trace_id=r["trace_id"],
            fund_code=r["fund_code"],
            period=r["period"],
            generated_at=r.get("generated_at"),
            schema_version=r.get("schema_version"),
            graph_node_count=r.get("graph_node_count", 0),
            graph_edge_count=r.get("graph_edge_count", 0),
            warning_count=r.get("warning_count", 0),
            error_count=r.get("error_count", 0),
            size_bytes=r.get("size_bytes", 0),
        )
        for r in raw
    ]
    return CommentTraceListResponseDTO(meta=_wc_meta(), traces=items)


@router.get(
    "/admin/comment-trace/latest",
    response_model=CommentTraceFullResponseDTO,
    tags=["admin"],
    summary="가장 최근 comment trace (R4)",
)
def get_latest_comment_trace(
    period: str | None = Query(default=None,
                                pattern=r"^\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$"),
    fund: str | None = Query(default=None, min_length=1, max_length=32,
                              pattern=r"^[A-Za-z0-9_]+$"),
) -> CommentTraceFullResponseDTO:
    payload = _ctg.load_latest_trace(period=period, fund=fund)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMMENT_TRACE_NOT_FOUND",
                     "message": "no comment trace found"},
        )
    tid = payload.get("trace_id") or "unknown"
    return CommentTraceFullResponseDTO(
        meta=_wc_meta(), trace_id=tid, payload=payload,
    )


@router.get(
    "/admin/comment-trace/{trace_id}",
    response_model=CommentTraceFullResponseDTO,
    tags=["admin"],
    summary="특정 comment trace by ID (R4)",
)
def get_comment_trace_by_id(
    trace_id: str = FastAPIPath(...,
                                  pattern=r"^[A-Za-z0-9_]+@\d{4}-(?:0[1-9]|1[0-2]|Q[1-4])$",
                                  min_length=1, max_length=64),
) -> CommentTraceFullResponseDTO:
    try:
        payload = _ctg.load_trace_by_id(trace_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "COMMENT_TRACE_INVALID_ID", "message": str(exc)},
        )
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COMMENT_TRACE_NOT_FOUND",
                     "message": f"trace {trace_id!r} not found"},
        )
    return CommentTraceFullResponseDTO(
        meta=_wc_meta(), trace_id=trace_id, payload=payload,
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


# ──────────────────────────────────────────────────────────────────
# R9-B: Wiki Context Pack viewer + raw wiki page reader (read-only)
# ──────────────────────────────────────────────────────────────────

from ..schemas.wiki_context_pack import (
    WikiContextPackPeriodItemDTO,
    WikiContextPackPeriodsResponseDTO,
    WikiContextPackResponseDTO,
    WikiContextPackSummaryDTO,
    WikiPackStage,
)
from ..schemas.wiki_page import WikiPageResponseDTO
from ..services import wiki_context_pack_gateway as _wcp
from ..services import wiki_page_gateway as _wpg


@router.get(
    "/admin/wiki-context-pack/periods",
    response_model=WikiContextPackPeriodsResponseDTO,
    tags=["admin"],
    summary="Wiki context pack monthly period 후보 목록 (R9-B)",
)
def list_wiki_context_pack_periods() -> WikiContextPackPeriodsResponseDTO:
    items_raw = _wcp.list_periods()
    items = [
        WikiContextPackPeriodItemDTO(
            period_key=r["period_key"],
            claim_store_exists=bool(r["claim_store_exists"]),
            claim_count=r.get("claim_count"),
        )
        for r in items_raw
    ]
    return WikiContextPackPeriodsResponseDTO(meta=_wc_meta(), periods=items)


@router.get(
    "/admin/wiki-context-pack",
    response_model=WikiContextPackResponseDTO,
    tags=["admin"],
    summary="Wiki context pack 미리보기 (R9-B, read-only)",
    description=(
        "`build_wiki_context_pack` 산출물을 그대로 노출. LLM 호출 0, "
        "운영 wiki/claims/report_output 변경 0. admin/debug 전용. "
        "R9-B.5 — period_type='quarterly' 시 period_key 가 YYYY-QX 형식이면 "
        "자동 unpacking, 또는 period_keys CSV (예 '2026-01,2026-02,2026-03') "
        "로 명시 가능. monthly path 는 회귀 없음."
    ),
)
def get_wiki_context_pack(
    period_key: str = Query(
        ..., pattern=r"^\d{4}-(?:(?:0[1-9]|1[0-2])|Q[1-4])$",
    ),
    stage: WikiPackStage = Query("market_debate"),
    period_type: str = Query("monthly",
                              pattern=r"^(?:monthly|quarterly)$"),
    period_keys: str | None = Query(default=None, max_length=256),
    fund_code: str | None = Query(default=None, max_length=32,
                                   pattern=r"^[A-Za-z0-9_]+$"),
    max_pages: int = Query(12, ge=1, le=64),
    body_excerpt_chars: int = Query(700, ge=80, le=4000),
    include_debate_memory: bool = Query(False),
) -> WikiContextPackResponseDTO:
    fc = fund_code.strip() if fund_code else None
    if fc == "":
        fc = None
    if stage == "fund_comment" and not fc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "WIKI_PACK_FUND_REQUIRED",
                "message": "fund_code is required when stage='fund_comment'",
            },
        )
    # R9-B.5 — period_type / period_keys 정합성 가드
    try:
        keys_list = _wcp.parse_period_keys_csv(period_keys)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "WIKI_PACK_INVALID_PERIOD_KEYS",
                     "message": str(exc)},
        )
    if period_type == "monthly":
        if not _wcp.PERIOD_MONTHLY_RE.fullmatch(period_key):
            raise HTTPException(
                status_code=400,
                detail={"code": "WIKI_PACK_INVALID_REQUEST",
                         "message": f"period_type='monthly' requires "
                                    f"period_key YYYY-MM (got {period_key!r})"},
            )
        if keys_list:
            raise HTTPException(
                status_code=400,
                detail={"code": "WIKI_PACK_INVALID_REQUEST",
                         "message": "period_keys is only valid when "
                                    "period_type='quarterly'"},
            )
    else:  # quarterly
        if not (_wcp.PERIOD_QUARTER_RE.fullmatch(period_key) or keys_list):
            raise HTTPException(
                status_code=400,
                detail={"code": "WIKI_PACK_INVALID_REQUEST",
                         "message": "period_type='quarterly' requires "
                                    "period_key YYYY-QX OR period_keys CSV "
                                    "(e.g. '2026-01,2026-02,2026-03')"},
            )
    try:
        pack = _wcp.build_pack(
            period_key=period_key,
            stage=stage,
            period_type=period_type,
            period_keys=keys_list,
            fund_code=fc,
            max_pages=max_pages,
            body_excerpt_chars=body_excerpt_chars,
            include_debate_memory=include_debate_memory,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "WIKI_PACK_INVALID_REQUEST", "message": str(exc)},
        )
    summary_dict = _wcp.extract_summary(pack)
    return WikiContextPackResponseDTO(
        meta=_wc_meta(),
        period_key=period_key,
        period_keys=pack.get("period_keys") or [period_key],
        period_type=pack.get("period_type") or period_type,
        stage=stage,
        fund_code=fc,
        summary=WikiContextPackSummaryDTO(**summary_dict),
        pack=pack,
    )


@router.get(
    "/admin/wiki-page",
    response_model=WikiPageResponseDTO,
    tags=["admin"],
    summary="Wiki page raw markdown 본문 조회 (R9-B, read-only)",
    description=(
        "WIKI_ROOT 산하 .md 파일 1건을 frontmatter + body 로 반환. "
        "path traversal 차단."
    ),
)
def get_wiki_page(
    path: str = Query(..., min_length=1, max_length=512),
) -> WikiPageResponseDTO:
    try:
        page = _wpg.load_page(path)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "WIKI_PAGE_INVALID_PATH", "message": str(exc)},
        )
    if page is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "WIKI_PAGE_NOT_FOUND",
                     "message": f"page {path!r} not found"},
        )
    return WikiPageResponseDTO(meta=_wc_meta(), **page)
