import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..schemas.admin import (
    AdminEvidenceQualityResponseDTO,
    AdminEvidenceQualityRowDTO,
)
from ..schemas.meta import BaseMeta, SourceBreakdown


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
