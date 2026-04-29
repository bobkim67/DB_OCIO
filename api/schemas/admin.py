from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from .meta import BaseMeta


DebateStatus = Literal[
    "not_generated",
    "draft_generated",
    "edited",
    "approved",
]


class AdminEvidenceQualityRowDTO(BaseModel):
    """_evidence_quality.jsonl 의 한 line.

    실파일 필드 (2026-04-22 조사):
      period, fund_code, debated_at, total_refs, ref_mismatches,
      tense_mismatches, mismatch_rate, evidence_count, critical_warnings
    """
    period: str | None = None
    fund_code: str | None = None
    debated_at: datetime | None = None
    total_refs: int | None = None
    ref_mismatches: int | None = None
    tense_mismatches: int | None = None
    mismatch_rate: float | None = None
    evidence_count: int | None = None
    critical_warnings: int | None = None
    raw: dict[str, Any]

    model_config = {"extra": "ignore"}


class AdminEvidenceQualityResponseDTO(BaseModel):
    meta: BaseMeta
    file_path: str
    total_lines: int
    returned: int
    malformed: int
    rows: list[AdminEvidenceQualityRowDTO]


class AdminDebateStatusResponseDTO(BaseModel):
    """report_output/{period}/{fund}.{input,draft,final}.json 상태 + 본문.

    Read-only. input은 summary만, draft/final은 본문 dict 그대로 노출.
    """
    meta: BaseMeta
    period: str
    fund_code: str
    status: DebateStatus
    has_input: bool
    has_draft: bool
    has_final: bool
    input_summary: dict[str, Any] | None = None
    draft_body: dict[str, Any] | None = None
    final_body: dict[str, Any] | None = None


class AdminDebatePeriodsResponseDTO(BaseModel):
    """report_output/ 하위 기간 디렉토리 목록 (read-only 스캔)."""
    meta: BaseMeta
    periods: list[str]
