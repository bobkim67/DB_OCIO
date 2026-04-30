from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from .meta import BaseMeta


# ──────────────────────────────────────────────────────────────────────
# Enrichment source labels
# ──────────────────────────────────────────────────────────────────────
# evidence_annotations / related_news / evidence_quality / validation_summary
# 4개 섹션은 lineage guard 적용 — `approved` / `unavailable` 두 값만 노출.
# (admin/debug용 내부 라벨 — final_json / draft_json / evidence_quality_jsonl —
# 은 별도 필드 `internal_source`에 격리한다.)
EnrichmentSource = Literal[
    "approved",      # 승인본과 lineage 일치 (client 노출 가능)
    "unavailable",   # 데이터 없음 또는 lineage 불일치/검증불가
]


# indicator_chart 전용 source — lineage 와 독립적이며 approved final 의 period
# 범위로 read-time 합성한 macro context 임을 명시한다.
IndicatorChartSource = Literal[
    "macro_timeseries",  # approved final 의 period 로 합성한 reference macro context
    "unavailable",       # 데이터 없음 / 합성 실패
]


# 내부 raw source (admin/debug 진단용). client UI에는 표시하지 않는다.
InternalEnrichmentSource = Literal[
    "final_json",
    "draft_json",
    "evidence_quality_jsonl",
    "macro_timeseries",
    "unavailable",
]


# Final.approved_at 또는 approved_debate_run_id 와 enrichment 데이터 정합성.
#
# 규칙 (위가 우선):
#   1) final.approved_debate_run_id 가 있으면 ID strict matching 적용:
#        - matched_by_id : ID 일치 (lineage 명시 검증, client 노출 가능)
#        - id_mismatch   : ID 불일치 또는 부재 (timestamp safe 여도 차단)
#   2) final.approved_debate_run_id 가 없으면 (legacy final) timestamp fallback:
#        - matched / older_than_or_equal_final / newer_than_final / unverifiable
#   3) 데이터 자체가 없으면 unavailable.
SourceConsistencyStatus = Literal[
    "matched_by_id",              # ID strict 일치 (P1-① 권장 경로)
    "id_mismatch",                # ID 불일치 또는 부재 (final 에 ID 있을 때)
    "matched",                    # legacy: approved_at == 데이터 timestamp
    "older_than_or_equal_final",  # legacy: 데이터 timestamp <= approved_at
    "newer_than_final",           # 데이터 timestamp >  approved_at (차단)
    "unverifiable",               # timestamp 누락 또는 파싱 실패
    "unavailable",                # 결합 대상 데이터 자체가 없음
]


# ──────────────────────────────────────────────────────────────────────
# Sub-DTOs (모두 optional / 빈 list 허용)
# ──────────────────────────────────────────────────────────────────────

class EvidenceAnnotationDTO(BaseModel):
    """draft.json `evidence_annotations` 항목 1건.

    원본: market_research debate_engine 산출.
    값이 없는 필드는 None 허용 (예: salience_explanation 누락 시).
    """
    ref: int
    article_id: str | None = None
    title: str | None = None
    url: str | None = None
    source: str | None = None
    date: str | None = None
    topic: str | None = None
    all_topics: list[str] = []
    salience: float | None = None
    salience_explanation: str | None = None


class RelatedNewsDTO(BaseModel):
    """draft.json `related_news` 항목. evidence_annotations와 같은 shape이지만
    debate에 직접 인용되지 않은 보조 기사들."""
    ref: int | None = None
    article_id: str | None = None
    title: str | None = None
    url: str | None = None
    source: str | None = None
    date: str | None = None
    topic: str | None = None
    all_topics: list[str] = []
    salience: float | None = None
    salience_explanation: str | None = None


class EvidenceQualitySummaryDTO(BaseModel):
    """draft.json `evidence_quality` 또는 _evidence_quality.jsonl 집계.

    카운트 의미 분리 (의미 혼동을 막기 위해 명시적 alias 제공):
      - cited_ref_count       = 본문에서 [ref:N] 으로 인용된 ref 개수 (= 기존 total_refs)
      - selected_evidence_count = debate에 선정된 evidence article 개수
                                  (= 기존 evidence_count, 인용되지 않은 보조 기사 포함 가능)
      - uncited_evidence_count  = selected_evidence_count − cited_ref_count
                                  (음수 방지를 위해 max(0, ...) 적용)
      - ref_mismatch_count    = ref 오매핑 건수 (= 기존 ref_mismatches)

    mismatch_rate 정의: `ref_mismatch_count / cited_ref_count`
                        (selected evidence 기준이 아닌 인용된 ref 기준)
    """
    # 신규 명시적 필드 (권장)
    cited_ref_count: int | None = None
    selected_evidence_count: int | None = None
    uncited_evidence_count: int | None = None
    ref_mismatch_count: int | None = None

    # 기존 필드 (backward compat — 동일 값 mirror)
    total_refs: int | None = None
    ref_mismatches: int | None = None

    tense_mismatches: int | None = None
    mismatch_rate: float | None = None
    evidence_count: int | None = None
    critical_warnings: int | None = None
    debated_at: str | None = None
    coverage_available_topics: int | None = None
    coverage_referenced_topics: int | None = None
    coverage_unreferenced_topics: list[str] = []
    numeric_sentences_total: int | None = None
    uncited_numeric_count: int | None = None


class ValidationWarningDTO(BaseModel):
    type: str
    message: str
    severity: str  # critical | warning | info
    ref_no: int | None = None


class ValidationSummaryDTO(BaseModel):
    """draft.json `validation_summary`."""
    sanitize_warnings: list[ValidationWarningDTO] = []
    warning_counts: dict[str, int] = {}


class IndicatorPointDTO(BaseModel):
    """단일 시점.

    - `value`: 첫 유효 시점을 100 으로 한 normalized index (시각화 기본값).
    - `raw_value`: 원 macro 값 (tooltip / 디버그용).
    """
    date: str          # YYYY-MM-DD
    value: float       # normalized — first valid point = 100
    raw_value: float   # 원 macro 값


class IndicatorSeriesDTO(BaseModel):
    """report 기간 범위로 잘라 합성한 단일 series.

    base_date / base_value 는 normalization 의 기준점:
      `value(t) = raw_value(t) / base_value * 100.0`
    """
    key: str                         # public key (예: "USDKRW", "PE_SP500")
    label: str                       # 사람 친화 라벨 (예: "USD/KRW", "PE 12M Fwd (SPY)")
    unit: str | None = None          # macro_service 의 unit literal
    points: list[IndicatorPointDTO] = []
    base_date: str | None = None     # normalization 기준일 (첫 유효 시점)
    base_value: float | None = None  # normalization 기준값 (raw_value)


class IndicatorChartDTO(BaseModel):
    """report 기간에 맞춰 read-time 합성된 macro context 차트.

    **중요**: indicator_chart 는 approved final 에 저장된 근거 데이터가 아니라,
    승인된 보고서 기간에 맞춰 조회 시점에 합성한 참고용 macro timeseries 다.
    lineage guard (matched_by_id / id_mismatch / newer_than_final 등) 와 독립적으로
    생성되며, client 에는 approved final 이 확인된 경우에만 노출된다.

    source 라벨도 다른 enrichment 와 분리:
      - "macro_timeseries": 합성 성공 (approved 가 아닌 별도 source)
      - "unavailable": 합성 실패 또는 series 부재
    """
    series: list[IndicatorSeriesDTO] = []
    unavailable_reason: str | None = None
    period_start: str | None = None  # YYYY-MM-DD
    period_end: str | None = None    # YYYY-MM-DD


# ──────────────────────────────────────────────────────────────────────
# Enrichment wrapper (모든 섹션의 source/empty 메타)
# ──────────────────────────────────────────────────────────────────────

class ClientReportEnrichmentDTO(BaseModel):
    """Client viewer (`/api/market-report`, `/api/funds/{fund}/report`) 응답에 들어가는
    enrichment 모델. **내부 source 라벨과 raw reason 메시지는 절대 포함되지 않는다.**

    노출 필드:
      - evidence_annotations / related_news / evidence_quality / validation_summary
        / indicator_chart
      - 각 섹션의 `*_source` 는 `"approved" | "unavailable"` 두 값만
      - source_consistency_status: 전체 lineage 진단 (enum)
      - source_consistency_note: client 안전 살균된 한 줄 안내
        (내부 파일명 / draft / jsonl 같은 용어 미포함)

    빈 list/null이면 React 측에서 섹션 hide.
    """
    evidence_annotations: list[EvidenceAnnotationDTO] = []
    evidence_annotations_source: EnrichmentSource = "unavailable"

    related_news: list[RelatedNewsDTO] = []
    related_news_source: EnrichmentSource = "unavailable"

    evidence_quality: EvidenceQualitySummaryDTO | None = None
    evidence_quality_source: EnrichmentSource = "unavailable"

    validation_summary: ValidationSummaryDTO | None = None
    validation_summary_source: EnrichmentSource = "unavailable"

    indicator_chart: IndicatorChartDTO | None = None
    # indicator_chart 는 lineage 와 독립적인 macro context — source 도 별도 enum.
    indicator_chart_source: IndicatorChartSource = "unavailable"

    source_consistency_status: SourceConsistencyStatus = "unavailable"
    source_consistency_note: str | None = None


class InternalReportEnrichmentDTO(BaseModel):
    """Service 내부에서만 사용하는 full enrichment (admin/debug 진단용).

    Client 응답에는 절대 그대로 직렬화되지 않는다. 향후 admin endpoint를 만들 때
    이 모델을 base 로 사용 (internal_source / raw reason 노출 가능).

    Lineage 정합성:
      - 각 섹션의 raw 데이터(draft/jsonl)는 final.approved_at 보다 timestamp가
        같거나 이른 경우에만 client에 노출 (`source="approved"`).
      - timestamp가 newer_than_final 이거나 unverifiable 인 경우, client viewer는
        해당 섹션을 unavailable 로 처리한다 (보수적 차단).
      - 내부 source 라벨 (draft_json / evidence_quality_jsonl 등)은 admin/debug용
        `internal_source` 필드에 격리. client UI는 `*_source` 만 본다.
    """
    evidence_annotations: list[EvidenceAnnotationDTO] = []
    evidence_annotations_source: EnrichmentSource = "unavailable"
    evidence_annotations_internal_source: InternalEnrichmentSource = "unavailable"

    related_news: list[RelatedNewsDTO] = []
    related_news_source: EnrichmentSource = "unavailable"
    related_news_internal_source: InternalEnrichmentSource = "unavailable"

    evidence_quality: EvidenceQualitySummaryDTO | None = None
    evidence_quality_source: EnrichmentSource = "unavailable"
    evidence_quality_internal_source: InternalEnrichmentSource = "unavailable"

    validation_summary: ValidationSummaryDTO | None = None
    validation_summary_source: EnrichmentSource = "unavailable"
    validation_summary_internal_source: InternalEnrichmentSource = "unavailable"

    indicator_chart: IndicatorChartDTO | None = None
    # indicator_chart 는 lineage 와 독립적인 macro context — source 도 별도 enum.
    indicator_chart_source: IndicatorChartSource = "unavailable"
    indicator_chart_internal_source: InternalEnrichmentSource = "unavailable"

    # Lineage 정합성 진단 (전체 enrichment 단위, admin/debug 노출용)
    source_consistency_status: SourceConsistencyStatus = "unavailable"
    source_consistency_reason: str | None = None


# 기존 이름 보존 (admin/debug 용도). 내부 모델 alias.
ReportEnrichmentDTO = InternalReportEnrichmentDTO


# ──────────────────────────────────────────────────────────────────────
# Top-level DTO
# ──────────────────────────────────────────────────────────────────────

class ReportFinalDTO(BaseModel):
    """report_output/{period}/{fund}.final.json 의 client-노출 필드.

    실파일 필드 (2026-04-29 조사):
      approved, approved_at, approved_by, consensus_points, tail_risks,
      cost_usd, final_comment, fund_code, generated_at, model, period, status

    Client에 미노출:
      - cost_usd (운영원가)
      - status (approved 필터링 후 의미 없음)

    빈 list 가능: consensus_points / tail_risks (펀드 코멘트는 보통 비어 있음).

    enrichment: 읽기 시점에 draft.json + _evidence_quality.jsonl 에서 결합.
    final.json 원본은 patch하지 않음. 모든 enrichment 섹션은 빈 값 허용.
    """
    period: str
    fund_code: str
    final_comment: str
    generated_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    model: str | None = None
    consensus_points: list[str] = []
    tail_risks: list[str] = []
    enrichment: ClientReportEnrichmentDTO = ClientReportEnrichmentDTO()


class ReportFinalResponseDTO(BaseModel):
    meta: BaseMeta
    data: ReportFinalDTO


class ReportApprovedPeriodsResponseDTO(BaseModel):
    """approved=true 인 final.json 이 존재하는 기간 목록 (정렬: 내림차순)."""
    meta: BaseMeta
    fund_code: str  # 시장 코멘트는 "_market"
    periods: list[str]
