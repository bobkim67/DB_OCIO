import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..schemas.admin import (
    AdminDebatePeriodsResponseDTO,
    AdminDebateStatusResponseDTO,
    AdminEvidenceQualityResponseDTO,
    AdminEvidenceQualityRowDTO,
)
from ..schemas.meta import BaseMeta, SourceBreakdown
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
