from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from .meta import BaseMeta
from .report import InternalReportEnrichmentDTO


DebateStatus = Literal[
    "not_generated",
    "draft_generated",
    "edited",
    "approved",
]


# admin/debug enrichment endpoint 전용 final 상태.
# client endpoint 의 approved-only 가드와 다름:
#   - approved: final.json approved=true
#   - final_unapproved: final.json 존재하지만 approved=false (client 라우터는 404, admin 은 read-only 노출)
#   - draft_only: final 부재 + draft 존재
#   - not_generated: final/draft 모두 부재
ReportEnrichmentFinalStatus = Literal[
    "approved",
    "final_unapproved",
    "draft_only",
    "not_generated",
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


# ──────────────────────────────────────────────────────────────────────────
# Admin / Debug Report Enrichment Diagnosis
# ──────────────────────────────────────────────────────────────────────────
# 운영 주의: 이 endpoint는 인증 없는 환경에서는 보안 경계가 아니다.
# 외부 노출 운영환경에서는 인증/권한 가드를 별도로 적용해야 한다.

class AdminEnrichmentJsonlRowDTO(BaseModel):
    """`_evidence_quality.jsonl` row — admin 진단용 명시 필드 + count alias.

    카운트 alias 는 evidence_quality DTO 와 동일한 의미 분리:
      - cited_ref_count       = total_refs (본문 인용 ref 수)
      - selected_evidence_count = evidence_count (선정 evidence 수)
      - uncited_evidence_count  = max(0, selected − cited)
      - ref_mismatches          = ref 오매핑 (alias 없이 그대로)
    """
    debate_run_id: str | None = None
    debated_at: datetime | None = None
    total_refs: int | None = None
    cited_ref_count: int | None = None
    selected_evidence_count: int | None = None
    uncited_evidence_count: int | None = None
    evidence_count: int | None = None
    ref_mismatches: int | None = None
    tense_mismatches: int | None = None
    mismatch_rate: float | None = None
    critical_warnings: int | None = None


class AdminReportEnrichmentResponseDTO(BaseModel):
    """admin/debug 전용 enrichment 진단 응답.

    Client endpoint (`/api/market-report`, `/api/funds/{fund}/report`) 와의 차이:
      - client: approved=true 인 final 만 노출, internal_source / raw reason / debate_run_id
                미노출, ClientReportEnrichmentDTO 반환.
      - admin/debug: approved=false 인 final 도 `final_unapproved` 상태로 read-only 노출.
                    InternalReportEnrichmentDTO (internal_source + raw reason 포함) 반환.
                    debate_run_id / approved_debate_run_id / draft_run_id 모두 노출.

    운영 주의: 이 endpoint 는 내부망/개발자용 read-only 진단 endpoint 이며,
    외부 노출 운영환경에서는 인증/권한 가드가 필요하다.
    """
    meta: BaseMeta
    period: str
    fund_code: str
    final_status: ReportEnrichmentFinalStatus

    # final.json 메타 (final 부재 시 None)
    approved_at: datetime | None = None
    approved_debate_run_id: str | None = None

    # draft.json 메타 (draft 부재 시 None)
    draft_run_id: str | None = None
    draft_generated_at: datetime | None = None

    # _evidence_quality.jsonl 의 period+fund 매칭 row (정렬: debated_at desc).
    # admin 이라도 무제한 반환은 피한다 (기본 limit=100, max=500).
    jsonl_rows: list[AdminEnrichmentJsonlRowDTO] = []
    jsonl_returned: int = 0
    jsonl_total_matched: int = 0

    # internal enrichment — internal_source / raw reason 그대로 노출.
    # final/draft 둘 다 부재 시 None.
    enrichment: InternalReportEnrichmentDTO | None = None
