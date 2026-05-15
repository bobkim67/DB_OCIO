"""Wiki Context Pack DTO (R9-B viewer endpoint).

`build_wiki_context_pack` (market_research/report/wiki_context_pack_builder.py)
산출물을 그대로 노출하기 위한 read-only wrapper.

Pack payload 자체는 dict[str, Any] 로 통과시킨다 (schema evolve 호환).
DTO 는 list/summary 와 meta wrapping 만 정형화.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from .meta import BaseMeta


WikiPackStage = Literal[
    "market_debate",
    "fund_comment",
    "quarterly_debate",
    "admin_preview",
]


class WikiContextPackPeriodItemDTO(BaseModel):
    """Claim store JSON (period 별) discovery 결과 1 row.

    builder 는 monthly period_key (YYYY-MM) 만 받는다. UI 선택지 채우기용.
    """
    period_key: str
    claim_store_exists: bool
    claim_count: int | None = None


class WikiContextPackPeriodsResponseDTO(BaseModel):
    meta: BaseMeta
    periods: list[WikiContextPackPeriodItemDTO]


class WikiContextPackSummaryDTO(BaseModel):
    """source_trace 의 핵심 카운터만 추려 dashboard 용으로 노출."""
    wiki_pages_considered: int
    wiki_pages_selected: int
    selected_wiki_paths: list[str]
    selected_by_directory: dict[str, int]
    source_type_counts: dict[str, int]
    selected_claim_ids: list[str]
    selected_related_group_ids: list[str]
    claim_store_selected_count: int
    matched_wiki_claim_count: int
    claim_store_to_wiki_join_rate: float | None = None
    source_cutoff_violations: int


class WikiContextPackResponseDTO(BaseModel):
    """Full pack response.

    - ``summary`` — source_trace 의 핵심 필드 (UI 가 자주 쓰는 것)
    - ``pack`` — builder 가 만든 raw dict 그대로
    """
    meta: BaseMeta
    period_key: str
    # R9-B.5 — quarterly union 일 때 unpacked monthly keys 노출 (예 ['2026-01',
    # '2026-02','2026-03']). monthly path 는 [period_key] 단일 원소 list.
    period_keys: list[str] = []
    period_type: str = "monthly"
    stage: WikiPackStage
    fund_code: str | None = None
    summary: WikiContextPackSummaryDTO
    pack: dict[str, Any]
