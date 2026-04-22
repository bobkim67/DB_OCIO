from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .meta import BaseMeta


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
