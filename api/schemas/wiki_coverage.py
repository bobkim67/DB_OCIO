"""R3-c DTO: Wiki coverage report.

list / latest / by-id endpoint 의 응답 schema. payload 자체는 도구가 생성한
JSON 그대로 (Any) — DTO 는 list 의 row + meta wrapping 만 정형화.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .meta import BaseMeta


class WikiCoverageGateSummaryDTO(BaseModel):
    total: int
    pass_count: int
    fail: int
    warning: int
    exit_code_expected: int
    fail_on_gate: bool


class WikiCoverageReportListItemDTO(BaseModel):
    id: str
    generated_at: str | None = None
    periods: list[str] = []
    funds: list[str] = []
    gate_summary: dict[str, Any] = {}
    size_bytes: int


class WikiCoverageReportListResponseDTO(BaseModel):
    meta: BaseMeta
    reports: list[WikiCoverageReportListItemDTO]


class WikiCoverageReportFullResponseDTO(BaseModel):
    """Full report — payload 는 도구 생성 JSON 그대로 (schema 진화 호환).

    DTO 는 wrapping 만. payload 의 schema_version / gate_summary / gate_results
    등은 Any 로 통과.
    """
    meta: BaseMeta
    report_id: str
    payload: dict[str, Any]
