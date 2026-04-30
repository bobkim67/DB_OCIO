import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..schemas.admin import (
    AdminDebatePeriodsResponseDTO,
    AdminDebateStatusResponseDTO,
    AdminEnrichmentJsonlRowDTO,
    AdminEvidenceQualityResponseDTO,
    AdminEvidenceQualityRowDTO,
    AdminReportEnrichmentResponseDTO,
    ReportEnrichmentFinalStatus,
)
from ..schemas.meta import BaseMeta, SourceBreakdown
from . import report_service as report_svc
from . import report_store_gateway as rsg


# debate-status: fund whitelist (9 운용 펀드 + 시장 debate)
ALLOWED_DEBATE_FUNDS: frozenset[str] = frozenset({
    "07G02", "07G03", "07G04",
    "08K88", "08N33", "08N81",
    "08P22", "2JM23", "4JM12",
    "_market",
})

_FUND_SAFE_RE = re.compile(r"^[A-Za-z0-9_]+$")


# api/services/admin_service.py → 프로젝트 루트 (api/의 상위)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_FILE = (
    PROJECT_ROOT
    / "market_research"
    / "data"
    / "report_output"
    / "_evidence_quality.jsonl"
)

_MAX_WARNINGS_LINES = 5
_HARD_LIMIT_CAP = 500
_DEFAULT_LIMIT = 100


def _make_row(obj: dict[str, Any]) -> AdminEvidenceQualityRowDTO:
    """dict → DTO. 실파일 필드 기준(2026-04-22 조사)."""
    return AdminEvidenceQualityRowDTO(
        period=obj.get("period"),
        fund_code=obj.get("fund_code"),
        debated_at=obj.get("debated_at"),
        total_refs=obj.get("total_refs"),
        ref_mismatches=obj.get("ref_mismatches"),
        tense_mismatches=obj.get("tense_mismatches"),
        mismatch_rate=obj.get("mismatch_rate"),
        evidence_count=obj.get("evidence_count"),
        critical_warnings=obj.get("critical_warnings"),
        raw=obj,
    )


def build_evidence_quality(
    limit: int | None = None,
    fund_code: str | None = None,
) -> AdminEvidenceQualityResponseDTO:
    warnings: list[str] = []
    sources: list[SourceBreakdown] = []
    malformed = 0
    parsed: list[dict[str, Any]] = []
    total_lines = 0
    file_path_rel = str(
        EVIDENCE_FILE.relative_to(PROJECT_ROOT)
        if EVIDENCE_FILE.is_absolute() and PROJECT_ROOT in EVIDENCE_FILE.parents
        else EVIDENCE_FILE
    ).replace("\\", "/")

    if not EVIDENCE_FILE.exists():
        return AdminEvidenceQualityResponseDTO(
            meta=BaseMeta(
                as_of_date=None,
                source="mock",
                sources=[],
                is_fallback=True,
                warnings=[f"file not found: {file_path_rel}"],
                generated_at=datetime.now(timezone.utc),
            ),
            file_path=file_path_rel,
            total_lines=0,
            returned=0,
            malformed=0,
            rows=[],
        )

    try:
        with EVIDENCE_FILE.open("r", encoding="utf-8") as f:
            for lineno, raw_line in enumerate(f, start=1):
                total_lines += 1
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    if len(warnings) < _MAX_WARNINGS_LINES:
                        warnings.append(f"parse failed at line {lineno}")
                    continue
                if isinstance(obj, dict):
                    parsed.append(obj)
    except Exception as exc:
        return AdminEvidenceQualityResponseDTO(
            meta=BaseMeta(
                as_of_date=None,
                source="mock",
                sources=[],
                is_fallback=True,
                warnings=[f"read failed: {type(exc).__name__}"],
                generated_at=datetime.now(timezone.utc),
            ),
            file_path=file_path_rel,
            total_lines=total_lines,
            returned=0,
            malformed=malformed,
            rows=[],
        )

    sources.append(SourceBreakdown(component="file", kind="db"))

    # fund_code 필터 (tail 자르기 전 적용)
    if fund_code:
        parsed = [r for r in parsed if r.get("fund_code") == fund_code]

    # tail limit
    effective_limit = min(limit, _HARD_LIMIT_CAP) if limit else _DEFAULT_LIMIT
    tail = parsed[-effective_limit:] if effective_limit > 0 else []

    rows: list[AdminEvidenceQualityRowDTO] = [_make_row(obj) for obj in tail]

    is_fallback = (len(parsed) == 0 and malformed > 0)
    if is_fallback:
        source_kind: str = "mock"
    elif malformed > 0:
        source_kind = "mixed"
        sources.append(SourceBreakdown(
            component="parse",
            kind="mock",
            note=f"{malformed} malformed lines",
        ))
    else:
        source_kind = "db"

    return AdminEvidenceQualityResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source=source_kind,          # type: ignore[arg-type]
            sources=sources,
            is_fallback=is_fallback,
            warnings=warnings,
            generated_at=datetime.now(timezone.utc),
        ),
        file_path=file_path_rel,
        total_lines=total_lines,
        returned=len(rows),
        malformed=malformed,
        rows=rows,
    )


# ──────────────────────────────────────────────────────────────────────────
# Debate Status (read-only)
# ──────────────────────────────────────────────────────────────────────────


def _validate_fund(fund_code: str) -> str:
    """fund_code 2중 방어:
      1) regex ^[A-Za-z0-9_]+$
      2) ALLOWED_DEBATE_FUNDS whitelist
    위반 시 422 (HTTPException).
    """
    fc = (fund_code or "").strip()
    if not fc or not _FUND_SAFE_RE.match(fc):
        raise HTTPException(status_code=422, detail="invalid fund format")
    if fc not in ALLOWED_DEBATE_FUNDS:
        raise HTTPException(status_code=422, detail="fund not in whitelist")
    return fc


def _validate_period(period: str) -> str:
    """period 형식 방어. router에서 1차 regex 차단했지만 service도 보강."""
    p = (period or "").strip()
    if not rsg.is_valid_period(p):
        raise HTTPException(status_code=422, detail="invalid period format")
    return p


def _summarize_input(payload: dict | None) -> dict | None:
    """input.json은 전체 노출 금지. 요약 키만 안전하게 추출."""
    if not isinstance(payload, dict):
        return None

    def _len_safe(v: Any) -> int:
        try:
            return len(v)
        except Exception:
            return 0

    evidence_pool = payload.get("evidence_pool") or payload.get("evidence") or []
    narrative = payload.get("narrative") or payload.get("narrative_blocks") or {}
    benchmarks = payload.get("benchmarks") or payload.get("bm") or {}
    warnings = payload.get("warnings") or []
    sources = payload.get("sources") or []

    sample: list[dict[str, Any]] = []
    if isinstance(evidence_pool, list):
        for item in evidence_pool[:5]:
            if not isinstance(item, dict):
                continue
            sample.append({
                "title": item.get("title"),
                "source": item.get("source"),
                "date": item.get("date"),
                "article_id": item.get("article_id") or item.get("_article_id"),
                "ref_id": item.get("ref_id"),
            })

    return {
        "prepared_at": payload.get("prepared_at"),
        "period": payload.get("period"),
        "fund_code": payload.get("fund_code"),
        "top_level_keys": sorted(payload.keys()),
        "evidence_count": _len_safe(evidence_pool),
        "warnings_count": _len_safe(warnings),
        "sources_count": _len_safe(sources),
        "narrative_sections_count": (
            _len_safe(narrative) if isinstance(narrative, (list, dict)) else 0
        ),
        "benchmark_keys": (
            sorted(benchmarks.keys()) if isinstance(benchmarks, dict)
            else (list(benchmarks)[:20] if isinstance(benchmarks, list) else [])
        ),
        "top_evidence_sample": sample,
    }


def build_debate_status(period: str, fund_code: str) -> AdminDebateStatusResponseDTO:
    p = _validate_period(period)
    fc = _validate_fund(fund_code)

    input_payload = rsg.load_input(p, fc)
    draft_payload = rsg.load_draft(p, fc)
    final_payload = rsg.load_final(p, fc)
    status = rsg.get_status(p, fc)

    sources: list[SourceBreakdown] = [
        SourceBreakdown(component="report_store", kind="db"),
    ]
    return AdminDebateStatusResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source="db",
            sources=sources,
            is_fallback=False,
            warnings=[],
            generated_at=datetime.now(timezone.utc),
        ),
        period=p,
        fund_code=fc,
        status=status,                          # type: ignore[arg-type]
        has_input=input_payload is not None,
        has_draft=draft_payload is not None,
        has_final=final_payload is not None,
        input_summary=_summarize_input(input_payload),
        draft_body=draft_payload,
        final_body=final_payload,
    )


def build_debate_periods() -> AdminDebatePeriodsResponseDTO:
    periods = rsg.list_period_dirs()
    return AdminDebatePeriodsResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source="db",
            sources=[SourceBreakdown(component="report_store", kind="db")],
            is_fallback=False,
            warnings=[],
            generated_at=datetime.now(timezone.utc),
        ),
        periods=periods,
    )


# ──────────────────────────────────────────────────────────────────────────
# Admin / Debug Report Enrichment Diagnosis
# ──────────────────────────────────────────────────────────────────────────
# 운영 주의: 이 endpoint 는 인증 없는 환경에서는 보안 경계가 아니다.
# 외부 노출 운영환경에서는 인증/권한 가드를 별도로 적용해야 한다.

_REPORT_ENRICHMENT_DEFAULT_LIMIT = 100
_REPORT_ENRICHMENT_MAX_LIMIT = 500


def _classify_final_status(
    final_payload: dict | None,
    draft_payload: dict | None,
) -> ReportEnrichmentFinalStatus:
    if final_payload:
        return "approved" if final_payload.get("approved") else "final_unapproved"
    if draft_payload:
        return "draft_only"
    return "not_generated"


def _make_jsonl_row(obj: dict[str, Any]) -> AdminEnrichmentJsonlRowDTO:
    """jsonl row → DTO. count alias 는 의미 분리:
      cited = total_refs / selected = evidence_count / uncited = max(0, selected-cited)
    """
    cited = obj.get("total_refs")
    selected = obj.get("evidence_count")
    uncited = None
    try:
        c = int(cited) if cited is not None else None
        s = int(selected) if selected is not None else None
        if c is not None and s is not None:
            uncited = max(0, s - c)
    except (TypeError, ValueError):
        uncited = None
    return AdminEnrichmentJsonlRowDTO(
        debate_run_id=obj.get("debate_run_id"),
        debated_at=obj.get("debated_at"),
        total_refs=cited,
        cited_ref_count=cited,
        selected_evidence_count=selected,
        uncited_evidence_count=uncited,
        evidence_count=selected,
        ref_mismatches=obj.get("ref_mismatches"),
        tense_mismatches=obj.get("tense_mismatches"),
        mismatch_rate=obj.get("mismatch_rate"),
        critical_warnings=obj.get("critical_warnings"),
    )


def _select_jsonl_rows(
    period: str,
    fund_code: str,
    limit: int,
) -> tuple[list[AdminEnrichmentJsonlRowDTO], int]:
    """period+fund 정확 매칭 + debated_at desc 정렬 + limit 적용.

    정렬 키: debated_at → created_at fallback. 둘 다 없으면 빈 문자열로 마지막에.
    """
    rows = rsg.read_evidence_quality_rows(period=period, fund_code=fund_code)

    def _key(r: dict[str, Any]) -> str:
        v = r.get("debated_at") or r.get("created_at")
        return str(v) if v is not None else ""

    rows_sorted = sorted(rows, key=_key, reverse=True)
    total = len(rows_sorted)
    capped = rows_sorted[:max(0, limit)]
    return [_make_jsonl_row(r) for r in capped], total


def build_report_enrichment_diagnosis(
    period: str,
    fund_code: str,
    limit: int | None = None,
) -> AdminReportEnrichmentResponseDTO:
    """admin/debug 전용 enrichment 진단.

    - approved=false 인 final 도 read-only 노출 (final_unapproved 상태)
    - InternalReportEnrichmentDTO 그대로 반환 (internal_source + raw reason)
    - jsonl_rows 는 period+fund 정확 매칭 + debated_at desc + limit
    """
    p = _validate_period(period)
    fc = _validate_fund(fund_code)

    # limit 정규화
    if limit is None:
        eff_limit = _REPORT_ENRICHMENT_DEFAULT_LIMIT
    else:
        eff_limit = min(max(1, int(limit)), _REPORT_ENRICHMENT_MAX_LIMIT)

    final_payload = rsg.load_final(p, fc)
    draft_payload = rsg.load_draft(p, fc)
    final_status = _classify_final_status(final_payload, draft_payload)

    # 응답 메타 추출
    approved_at = None
    approved_debate_run_id = None
    if final_payload:
        approved_at = final_payload.get("approved_at")
        v = final_payload.get("approved_debate_run_id")
        approved_debate_run_id = (
            str(v).strip() if v is not None and str(v).strip() else None
        )

    draft_run_id = None
    draft_generated_at = None
    if draft_payload:
        v = draft_payload.get("debate_run_id")
        draft_run_id = (
            str(v).strip() if v is not None and str(v).strip() else None
        )
        draft_generated_at = draft_payload.get("generated_at")

    # jsonl rows
    jsonl_rows, jsonl_total = _select_jsonl_rows(p, fc, eff_limit)

    # internal enrichment — final 부재 시 None.
    # final 이 있으면 approved 여부와 무관하게 lineage 진단 (final_unapproved 도 포함).
    internal_enrichment = None
    if final_payload is not None:
        internal_enrichment = report_svc.build_internal_report_enrichment(
            final_payload, p, fc,
        )

    return AdminReportEnrichmentResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source="db",
            sources=[SourceBreakdown(component="report_store", kind="db")],
            is_fallback=False,
            warnings=[],
            generated_at=datetime.now(timezone.utc),
        ),
        period=p,
        fund_code=fc,
        final_status=final_status,
        approved_at=approved_at,
        approved_debate_run_id=approved_debate_run_id,
        draft_run_id=draft_run_id,
        draft_generated_at=draft_generated_at,
        jsonl_rows=jsonl_rows,
        jsonl_returned=len(jsonl_rows),
        jsonl_total_matched=jsonl_total,
        enrichment=internal_enrichment,
    )
