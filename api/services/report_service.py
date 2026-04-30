"""Approved final.json 뷰어 서비스.

- 시장 코멘트 (`_market`): 펀드와 독립된 매크로 산출물
- 펀드 코멘트: 시장 코멘트 + 거래/편입 기반으로 작성된 fund-scoped 산출물

규약:
  - approved=true 인 final.json 만 client에 노출 (404 처리)
  - 읽기 전용. report_store.save_* 계열 절대 호출 금지
  - fund_code 화이트리스트: 9 운용 펀드. 시장 라우터는 `_market` 고정
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone

from fastapi import HTTPException

from ..schemas.meta import BaseMeta, SourceBreakdown
from ..schemas.report import (
    ClientReportEnrichmentDTO,
    EnrichmentSource,
    EvidenceAnnotationDTO,
    EvidenceQualitySummaryDTO,
    IndicatorChartDTO,
    IndicatorChartSource,
    IndicatorPointDTO,
    IndicatorSeriesDTO,
    InternalEnrichmentSource,
    InternalReportEnrichmentDTO,
    LinkedMarketEnrichmentDTO,
    RelatedNewsDTO,
    ReportApprovedPeriodsResponseDTO,
    ReportFinalDTO,
    ReportFinalResponseDTO,
    SourceConsistencyStatus,
    ValidationSummaryDTO,
    ValidationWarningDTO,
)
from . import macro_service
from . import report_store_gateway as rsg


# 펀드 코멘트 화이트리스트 (시장 `_market` 별도 라우터)
ALLOWED_REPORT_FUNDS: frozenset[str] = frozenset({
    "07G02", "07G03", "07G04",
    "08K88", "08N33", "08N81",
    "08P22", "2JM23", "4JM12",
})

_MARKET_FUND_CODE = "_market"
_FUND_SAFE_RE = re.compile(r"^[A-Za-z0-9_]+$")


# ──────────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────────

def _validate_period(period: str) -> str:
    p = (period or "").strip()
    if not rsg.is_valid_period(p):
        raise HTTPException(status_code=422, detail="invalid period format")
    return p


def _validate_fund(fund_code: str) -> str:
    fc = (fund_code or "").strip()
    if not fc or not _FUND_SAFE_RE.match(fc):
        raise HTTPException(status_code=422, detail="invalid fund format")
    if fc not in ALLOWED_REPORT_FUNDS:
        raise HTTPException(status_code=422, detail="fund not in whitelist")
    return fc


# ──────────────────────────────────────────────────────────────────────────
# DTO assembly
# ──────────────────────────────────────────────────────────────────────────

def _to_dto(payload: dict, period: str, fund_code: str) -> ReportFinalDTO:
    """final.json dict → DTO. payload는 approved=true 검증을 마쳤다고 가정.

    enrichment는 _build_enrichment() 가 별도로 채움 (read-time, final.json 불변).
    """
    cp = payload.get("consensus_points") or []
    tr = payload.get("tail_risks") or []
    # str로 변환 (혹시 dict 등이 섞여 들어온 경우 안전하게 처리)
    cp = [str(x) for x in cp if x is not None]
    tr = [str(x) for x in tr if x is not None]
    return ReportFinalDTO(
        period=payload.get("period") or period,
        fund_code=payload.get("fund_code") or fund_code,
        final_comment=str(payload.get("final_comment") or ""),
        generated_at=payload.get("generated_at"),
        approved_at=payload.get("approved_at"),
        approved_by=payload.get("approved_by"),
        model=payload.get("model"),
        consensus_points=cp,
        tail_risks=tr,
        enrichment=ClientReportEnrichmentDTO(),
    )


# ──────────────────────────────────────────────────────────────────────────
# Enrichment helpers (read-only, final.json 원본 불변)
# ──────────────────────────────────────────────────────────────────────────

def _coerce_evidence_annotation(item: dict) -> EvidenceAnnotationDTO | None:
    """evidence_annotation 1건을 DTO로. ref가 없으면 skip."""
    if not isinstance(item, dict):
        return None
    ref = item.get("ref")
    try:
        ref_int = int(ref) if ref is not None else None
    except (TypeError, ValueError):
        return None
    if ref_int is None:
        return None
    salience = item.get("salience")
    try:
        salience_f = float(salience) if salience is not None else None
    except (TypeError, ValueError):
        salience_f = None
    all_topics = item.get("all_topics")
    if not isinstance(all_topics, list):
        all_topics = []
    return EvidenceAnnotationDTO(
        ref=ref_int,
        article_id=item.get("article_id"),
        title=item.get("title"),
        url=item.get("url"),
        source=item.get("source"),
        date=item.get("date"),
        topic=item.get("topic"),
        all_topics=[str(t) for t in all_topics if t is not None],
        salience=salience_f,
        salience_explanation=item.get("salience_explanation"),
    )


def _coerce_related_news(item: dict) -> RelatedNewsDTO | None:
    if not isinstance(item, dict):
        return None
    ref = item.get("ref")
    try:
        ref_int = int(ref) if ref is not None else None
    except (TypeError, ValueError):
        ref_int = None
    salience = item.get("salience")
    try:
        salience_f = float(salience) if salience is not None else None
    except (TypeError, ValueError):
        salience_f = None
    all_topics = item.get("all_topics")
    if not isinstance(all_topics, list):
        all_topics = []
    return RelatedNewsDTO(
        ref=ref_int,
        article_id=item.get("article_id"),
        title=item.get("title"),
        url=item.get("url"),
        source=item.get("source"),
        date=item.get("date"),
        topic=item.get("topic"),
        all_topics=[str(t) for t in all_topics if t is not None],
        salience=salience_f,
        salience_explanation=item.get("salience_explanation"),
    )


def _coerce_validation(payload_section: dict) -> ValidationSummaryDTO | None:
    if not isinstance(payload_section, dict):
        return None
    raw_warnings = payload_section.get("sanitize_warnings") or []
    warnings: list[ValidationWarningDTO] = []
    for w in raw_warnings:
        if not isinstance(w, dict):
            continue
        wtype = str(w.get("type") or "")
        msg = str(w.get("message") or "")
        sev = str(w.get("severity") or "info")
        if not wtype and not msg:
            continue
        ref_no = w.get("ref_no")
        try:
            ref_no_i = int(ref_no) if ref_no is not None else None
        except (TypeError, ValueError):
            ref_no_i = None
        warnings.append(ValidationWarningDTO(
            type=wtype, message=msg, severity=sev, ref_no=ref_no_i,
        ))
    counts_raw = payload_section.get("warning_counts") or {}
    counts: dict[str, int] = {}
    if isinstance(counts_raw, dict):
        for k, v in counts_raw.items():
            try:
                counts[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    return ValidationSummaryDTO(
        sanitize_warnings=warnings,
        warning_counts=counts,
    )


def _coerce_quality(
    quality_section: dict | None,
    coverage_section: dict | None,
    jsonl_row: dict | None,
) -> EvidenceQualitySummaryDTO | None:
    """draft.json `evidence_quality` + `coverage_metrics` + jsonl row를 결합.

    값 우선순위 (위가 우선): draft.evidence_quality → jsonl row.
    draft.coverage_metrics 는 보완용 (coverage_* 필드만).

    카운트 의미 분리:
      - cited_ref_count = 본문 인용된 ref 수 (draft `total_refs`)
      - selected_evidence_count = debate가 선정한 evidence 수 (`evidence_count`)
      - uncited_evidence_count = max(0, selected - cited)
      - ref_mismatch_count = ref 오매핑 (`ref_mismatches`)
      - mismatch_rate = ref_mismatch_count / cited_ref_count (cited 기준)
    """
    has_any = any([
        isinstance(quality_section, dict) and quality_section,
        isinstance(coverage_section, dict) and coverage_section,
        isinstance(jsonl_row, dict) and jsonl_row,
    ])
    if not has_any:
        return None

    def _pick(*candidates):
        for c in candidates:
            if c is not None:
                return c
        return None

    def _i(v):
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _f(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    q = quality_section if isinstance(quality_section, dict) else {}
    c = coverage_section if isinstance(coverage_section, dict) else {}
    j = jsonl_row if isinstance(jsonl_row, dict) else {}

    unref = c.get("unreferenced_topics")
    if not isinstance(unref, list):
        unref = []

    cited = _i(_pick(q.get("total_refs"), j.get("total_refs")))
    selected = _i(_pick(q.get("evidence_count"), j.get("evidence_count")))
    mism = _i(_pick(q.get("ref_mismatches"), j.get("ref_mismatches")))
    uncited = None
    if cited is not None and selected is not None:
        uncited = max(0, selected - cited)

    return EvidenceQualitySummaryDTO(
        # 신규 명시 필드
        cited_ref_count=cited,
        selected_evidence_count=selected,
        uncited_evidence_count=uncited,
        ref_mismatch_count=mism,
        # backward-compat mirror
        total_refs=cited,
        ref_mismatches=mism,
        tense_mismatches=_i(
            _pick(q.get("tense_mismatches"), j.get("tense_mismatches"))),
        mismatch_rate=_f(
            _pick(q.get("mismatch_rate"), j.get("mismatch_rate"))),
        evidence_count=selected,
        critical_warnings=_i(j.get("critical_warnings")),
        debated_at=str(j.get("debated_at")) if j.get("debated_at") else None,
        coverage_available_topics=_i(c.get("available_topics_count")),
        coverage_referenced_topics=_i(c.get("referenced_topics_count")),
        coverage_unreferenced_topics=[str(t) for t in unref if t is not None],
        numeric_sentences_total=_i(c.get("numeric_sentences_total")),
        uncited_numeric_count=_i(c.get("uncited_numeric_count")),
    )


# ──────────────────────────────────────────────────────────────────────────
# Indicator chart — read-time macro context 합성 (lineage 독립)
# ──────────────────────────────────────────────────────────────────────────
# 정책 (io_contract v1.6 §9):
#   - indicator_chart 는 approved final 에 저장된 근거 데이터가 아니라,
#     승인된 보고서의 period 범위에 맞춰 read-time 합성한 reference macro context.
#   - lineage guard 와 독립적으로 생성되며, client 노출 조건은
#     "approved final 존재" 단 하나.
#   - source 라벨도 분리: "macro_timeseries" (합성 성공) / "unavailable".

# 기본 노출 series (1차) — MACRO_DATASETS 매핑 존재 키만.
_DEFAULT_INDICATOR_KEYS: tuple[str, ...] = ("USDKRW", "PE_SP500", "EPS_SP500")

# normalization 기준값. raw_value(t) / base_value * SCALE.
_INDEX_SCALE: float = 100.0


def _period_to_range(period: str) -> tuple[date, date] | None:
    """`YYYY-MM` / `YYYY-Q[1-4]` → (start, end). 미일치 시 None.

    예:
      '2026-04' → (2026-04-01, 2026-04-30)
      '2026-Q1' → (2026-01-01, 2026-03-31)
    """
    if not period or len(period) < 7:
        return None
    p = period.strip()
    if not rsg.is_valid_period(p):
        return None
    try:
        year = int(p[:4])
    except ValueError:
        return None
    tail = p[5:]
    if tail.startswith("Q"):
        try:
            q = int(tail[1:])
        except ValueError:
            return None
        if not 1 <= q <= 4:
            return None
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        start = date(year, start_month, 1)
        end_day = calendar.monthrange(year, end_month)[1]
        end = date(year, end_month, end_day)
        return start, end
    # YYYY-MM
    try:
        m = int(tail)
    except ValueError:
        return None
    if not 1 <= m <= 12:
        return None
    start = date(year, m, 1)
    end_day = calendar.monthrange(year, m)[1]
    end = date(year, m, end_day)
    return start, end


def _normalize_series_points(
    raw_points: list[tuple[date, float]],
) -> tuple[list[IndicatorPointDTO], date | None, float | None]:
    """raw (date, value) 리스트 → normalized IndicatorPointDTO 리스트.

    normalization: 첫 유효(non-NaN, non-zero) 시점을 base 로 잡아 100 = base.
    base_value 가 0 이면 normalize 불가 → 빈 리스트 반환 (skip).
    """
    base_date: date | None = None
    base_value: float | None = None
    out: list[IndicatorPointDTO] = []

    for d, v in raw_points:
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if base_value is None:
            if fv == 0:
                # 기준값 0 은 정규화 불가 — 다음 유효값까지 대기
                continue
            base_value = fv
            base_date = d
        # base 가 잡혔으면 모든 후속 값을 normalize
        if base_value is not None and base_value != 0:
            normalized = fv / base_value * _INDEX_SCALE
            out.append(IndicatorPointDTO(
                date=d.isoformat(),
                value=normalized,
                raw_value=fv,
            ))
    return out, base_date, base_value


def _build_indicator_chart(period: str) -> IndicatorChartDTO:
    """report period 에 맞춘 macro series 합성. lineage guard 와 독립."""
    rng = _period_to_range(period)
    if rng is None:
        return IndicatorChartDTO(
            series=[],
            unavailable_reason="invalid_period_format",
        )
    start_d, end_d = rng

    try:
        macro_resp = macro_service.build_macro_timeseries(
            keys=list(_DEFAULT_INDICATOR_KEYS),
            start_date=start_d.isoformat(),
        )
    except Exception:
        return IndicatorChartDTO(
            series=[],
            unavailable_reason="macro_service_failed",
            period_start=start_d.isoformat(),
            period_end=end_d.isoformat(),
        )

    out_series: list[IndicatorSeriesDTO] = []
    for s in macro_resp.series:
        # period 범위로 자르고 raw 추출
        windowed: list[tuple[date, float]] = []
        for p in s.points:
            d = p.date_ if hasattr(p, "date_") else p.date
            if not isinstance(d, date):
                continue
            if start_d <= d <= end_d:
                windowed.append((d, p.value))
        if not windowed:
            continue
        normalized, base_date, base_value = _normalize_series_points(windowed)
        if not normalized:
            continue
        out_series.append(IndicatorSeriesDTO(
            key=s.key,
            label=s.label or s.key,
            unit=s.unit,
            points=normalized,
            base_date=base_date.isoformat() if base_date else None,
            base_value=base_value,
        ))

    if not out_series:
        return IndicatorChartDTO(
            series=[],
            unavailable_reason="no_macro_data_in_period",
            period_start=start_d.isoformat(),
            period_end=end_d.isoformat(),
        )

    return IndicatorChartDTO(
        series=out_series,
        unavailable_reason=None,
        period_start=start_d.isoformat(),
        period_end=end_d.isoformat(),
    )


# ──────────────────────────────────────────────────────────────────────────
# Lineage 정합성 검증 (final.approved_at vs draft/jsonl timestamp)
# ──────────────────────────────────────────────────────────────────────────

# draft.json 에서 lineage 비교에 사용 가능한 timestamp 후보. 위가 우선.
_DRAFT_TIMESTAMP_KEYS = (
    "generated_at",
    "debated_at",
    "updated_at",
    "created_at",
)


def _parse_iso(v) -> datetime | None:
    """ISO datetime 문자열 또는 datetime 객체 → tz-naive datetime.

    파싱 실패 시 None. tz-aware는 UTC 기준 naive 로 정규화 (단순 비교용).
    """
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        # 'Z' suffix 처리
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is not None:
        try:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except (OverflowError, ValueError):
            return None
    return dt


def _approved_at_dt(final_payload: dict) -> datetime | None:
    return _parse_iso(final_payload.get("approved_at"))


def _approved_run_id(final_payload: dict) -> str | None:
    """final.approved_debate_run_id 추출. 빈 문자열은 None 처리."""
    v = final_payload.get("approved_debate_run_id")
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _payload_run_id(payload: dict) -> str | None:
    """draft / jsonl row 의 debate_run_id 추출."""
    v = payload.get("debate_run_id")
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _classify_by_id(
    final_run_id: str | None,
    data_run_id: str | None,
) -> SourceConsistencyStatus | None:
    """ID 기반 분류. final 에 ID 가 없으면 None (timestamp fallback 으로 위임).

    final 에 ID 가 있으면:
      - data_run_id 일치 → matched_by_id
      - data_run_id 누락/불일치 → id_mismatch (timestamp fallback 금지)
    """
    if not final_run_id:
        return None  # legacy final → caller가 timestamp fallback 사용
    if data_run_id and data_run_id == final_run_id:
        return "matched_by_id"
    return "id_mismatch"


def _draft_lineage_timestamp(draft_payload: dict) -> tuple[datetime | None, str | None]:
    """draft에서 가장 신뢰할 수 있는 timestamp + 사용한 키 반환."""
    for key in _DRAFT_TIMESTAMP_KEYS:
        v = draft_payload.get(key)
        dt = _parse_iso(v)
        if dt is not None:
            return dt, key
    return None, None


def _classify_consistency(
    approved_at: datetime | None,
    data_ts: datetime | None,
) -> SourceConsistencyStatus:
    """단일 timestamp 기준 lineage 분류."""
    if approved_at is None:
        # final.approved_at 자체가 없으면 비교 불가
        return "unverifiable"
    if data_ts is None:
        return "unverifiable"
    if data_ts == approved_at:
        return "matched"
    if data_ts < approved_at:
        return "older_than_or_equal_final"
    return "newer_than_final"


def _is_safe_for_client(status: SourceConsistencyStatus) -> bool:
    """client에 노출해도 안전한 lineage 상태인지.

    matched_by_id (ID strict 일치) + matched / older_than_or_equal_final (legacy
    timestamp fallback 안전) 만 허용. id_mismatch / newer_than_final / unverifiable
    / unavailable 은 모두 차단.
    """
    return status in ("matched_by_id", "matched", "older_than_or_equal_final")


def _to_external_source(
    internal: InternalEnrichmentSource,
    is_safe: bool,
) -> EnrichmentSource:
    """내부 source → client-facing source 변환.

    internal=unavailable 또는 lineage unsafe 면 unavailable.
    """
    if internal == "unavailable":
        return "unavailable"
    return "approved" if is_safe else "unavailable"


def _aggregate_consistency(
    statuses: list[SourceConsistencyStatus],
) -> SourceConsistencyStatus:
    """전체 enrichment 단위 정합성 집계.

    우선순위 (위 → 아래; 위가 우선 = 더 위험하거나 정보량이 큰 상태):
      id_mismatch > newer_than_final > unverifiable
        > matched_by_id > older_than_or_equal_final > matched > unavailable

    원칙: 한 섹션이라도 위험 신호가 있으면 전체에 반영. 안전한 섹션 중에서는
    더 강한 명시 검증(matched_by_id)이 우선.
    """
    if not statuses:
        return "unavailable"
    # 위험 신호 우선
    if "id_mismatch" in statuses:
        return "id_mismatch"
    if "newer_than_final" in statuses:
        return "newer_than_final"
    if "unverifiable" in statuses:
        return "unverifiable"
    # 안전 신호
    if "matched_by_id" in statuses:
        return "matched_by_id"
    if "older_than_or_equal_final" in statuses:
        return "older_than_or_equal_final"
    if "matched" in statuses:
        return "matched"
    return "unavailable"


def _build_enrichment(
    final_payload: dict,
    period: str,
    fund_code: str,
) -> InternalReportEnrichmentDTO:
    """final.json + draft.json + jsonl 결합. final.json 원본은 patch하지 않음.

    Lineage 정합성 (P1-① 강화):
      1) final.approved_debate_run_id 가 있으면 ID strict matching:
         - draft.debate_run_id 일치 → matched_by_id (client 노출 OK)
         - draft.debate_run_id 누락/불일치 → id_mismatch (timestamp fallback 금지)
         - jsonl row 도 동일 규칙. ID 일치하는 row 만 후보, 그 중 최신 1건.
      2) final.approved_debate_run_id 가 없으면 (legacy final) timestamp fallback:
         - draft/jsonl timestamp <= approved_at → safe
         - timestamp newer / 부재 → 차단
      3) 데이터 자체 부재 → unavailable.
      4) 내부 source 라벨은 admin/debug용으로만 internal_source 필드에 보존.
    """
    approved_at = _approved_at_dt(final_payload)
    approved_run_id = _approved_run_id(final_payload)

    # ── 1) draft 로딩 + lineage 분류 (ID 우선 → timestamp fallback)
    draft_payload = rsg.load_draft(period, fund_code) or {}
    draft_ts, draft_ts_key = _draft_lineage_timestamp(draft_payload)
    if draft_payload:
        id_status = _classify_by_id(approved_run_id, _payload_run_id(draft_payload))
        if id_status is not None:
            # ID 기반 분류 (final 에 ID 있음). timestamp fallback 금지.
            draft_status = id_status
        else:
            draft_status = _classify_consistency(approved_at, draft_ts)
    else:
        draft_status = "unavailable"
    draft_safe = _is_safe_for_client(draft_status)

    # ── 2) jsonl 로딩 + lineage 검증된 row만 사용 (ID 우선 → timestamp fallback)
    rows_all = rsg.read_evidence_quality_rows(period=period, fund_code=fund_code)
    safe_jsonl_rows: list[dict] = []
    if approved_run_id:
        # ID strict matching: row.debate_run_id == final.approved_debate_run_id 만 허용.
        for row in rows_all:
            if _payload_run_id(row) == approved_run_id:
                safe_jsonl_rows.append(row)
    else:
        # legacy: timestamp fallback
        for row in rows_all:
            ts = _parse_iso(row.get("debated_at") or row.get("created_at"))
            st = _classify_consistency(approved_at, ts)
            if _is_safe_for_client(st):
                safe_jsonl_rows.append(row)

    # 가장 최신 (lineage 안전 범위 내) row를 fallback 후보로
    jsonl_row = None
    jsonl_status: SourceConsistencyStatus = "unavailable"
    if safe_jsonl_rows:
        def _key(r: dict) -> str:
            v = r.get("debated_at") or r.get("created_at")
            return str(v) if v is not None else ""
        jsonl_row = sorted(safe_jsonl_rows, key=_key, reverse=True)[0]
        if approved_run_id:
            jsonl_status = "matched_by_id"
        else:
            jsonl_status = _classify_consistency(
                approved_at,
                _parse_iso(jsonl_row.get("debated_at") or jsonl_row.get("created_at")),
            )
    elif rows_all:
        # rows 는 있으나 안전 범위 내 row 가 없음
        if approved_run_id:
            jsonl_status = "id_mismatch"
        elif approved_at is None:
            jsonl_status = "unverifiable"
        else:
            jsonl_status = "newer_than_final"

    statuses_collected: list[SourceConsistencyStatus] = []

    # ── 3) evidence_annotations
    ea_internal: InternalEnrichmentSource = "unavailable"
    ea_raw = final_payload.get("evidence_annotations")
    if isinstance(ea_raw, list) and ea_raw:
        ea_internal = "final_json"
        ea_safe = True  # final 본문 자체 → 정의상 safe
        ea_status: SourceConsistencyStatus = "matched"
    else:
        raw = draft_payload.get("evidence_annotations")
        if isinstance(raw, list) and raw:
            ea_internal = "draft_json"
            ea_safe = draft_safe
            ea_status = draft_status
            ea_raw = raw
        else:
            ea_raw = []
            ea_safe = False
            ea_status = "unavailable"
    ea_dtos: list[EvidenceAnnotationDTO] = []
    for it in ea_raw or []:
        d = _coerce_evidence_annotation(it)
        if d is not None:
            ea_dtos.append(d)
    if not ea_dtos:
        ea_internal = "unavailable"
        ea_safe = False
    if ea_internal != "unavailable":
        statuses_collected.append(ea_status)
    # client-facing: lineage unsafe 면 비공개
    if not ea_safe:
        ea_dtos = []
    ea_external = _to_external_source(ea_internal, ea_safe)

    # ── 4) related_news
    rn_internal: InternalEnrichmentSource = "unavailable"
    rn_raw = final_payload.get("related_news")
    if isinstance(rn_raw, list) and rn_raw:
        rn_internal = "final_json"
        rn_safe = True
        rn_status: SourceConsistencyStatus = "matched"
    else:
        raw = draft_payload.get("related_news")
        if isinstance(raw, list) and raw:
            rn_internal = "draft_json"
            rn_safe = draft_safe
            rn_status = draft_status
            rn_raw = raw
        else:
            rn_raw = []
            rn_safe = False
            rn_status = "unavailable"
    rn_dtos: list[RelatedNewsDTO] = []
    for it in rn_raw or []:
        d = _coerce_related_news(it)
        if d is not None:
            rn_dtos.append(d)
    if not rn_dtos:
        rn_internal = "unavailable"
        rn_safe = False
    if rn_internal != "unavailable":
        statuses_collected.append(rn_status)
    if not rn_safe:
        rn_dtos = []
    rn_external = _to_external_source(rn_internal, rn_safe)

    # ── 5) evidence_quality (draft 우선 → jsonl 보조, 둘 다 lineage 검증)
    q_internal: InternalEnrichmentSource = "unavailable"
    q_safe = False
    q_status: SourceConsistencyStatus = "unavailable"
    q_section: dict | None = None
    cov_section: dict | None = None
    use_jsonl = False

    final_q = final_payload.get("evidence_quality")
    if isinstance(final_q, dict) and final_q:
        q_internal = "final_json"
        q_section = final_q
        cov_section = final_payload.get("coverage_metrics") if isinstance(
            final_payload.get("coverage_metrics"), dict) else None
        q_safe = True
        q_status = "matched"
    else:
        draft_q = draft_payload.get("evidence_quality")
        if isinstance(draft_q, dict) and draft_q:
            q_internal = "draft_json"
            q_section = draft_q
            cov_section = draft_payload.get("coverage_metrics") if isinstance(
                draft_payload.get("coverage_metrics"), dict) else None
            q_safe = draft_safe
            q_status = draft_status
        elif jsonl_row is not None:
            q_internal = "evidence_quality_jsonl"
            use_jsonl = True
            q_safe = True  # jsonl_row는 이미 lineage 검증된 row
            q_status = jsonl_status
        else:
            # rows가 있었으나 unsafe로 모두 차단된 경우
            if jsonl_status == "newer_than_final":
                q_status = "newer_than_final"
            elif jsonl_status == "unverifiable":
                q_status = "unverifiable"

    quality_dto = _coerce_quality(
        q_section, cov_section, jsonl_row if use_jsonl else None,
    )
    if quality_dto is None:
        q_internal = "unavailable"
        q_safe = False
    else:
        if q_internal != "unavailable":
            statuses_collected.append(q_status)
        if not q_safe:
            quality_dto = None

    # jsonl rows 가 모두 lineage 부적합으로 차단된 경우에도 위험 신호는
    # 전체 정합성에 반영 (그렇지 않으면 overall=unavailable 로 약화됨).
    if quality_dto is None and rows_all and jsonl_status in (
        "id_mismatch", "newer_than_final", "unverifiable",
    ):
        statuses_collected.append(jsonl_status)

    q_external = _to_external_source(q_internal, q_safe)

    # ── 6) validation_summary
    v_internal: InternalEnrichmentSource = "unavailable"
    v_safe = False
    v_status: SourceConsistencyStatus = "unavailable"
    v_section: dict | None = None

    final_v = final_payload.get("validation_summary")
    if isinstance(final_v, dict) and final_v:
        v_internal = "final_json"
        v_section = final_v
        v_safe = True
        v_status = "matched"
    else:
        draft_v = draft_payload.get("validation_summary")
        if isinstance(draft_v, dict) and draft_v:
            v_internal = "draft_json"
            v_section = draft_v
            v_safe = draft_safe
            v_status = draft_status

    validation_dto = (
        _coerce_validation(v_section) if isinstance(v_section, dict) else None
    )
    if validation_dto is None or (
        not validation_dto.sanitize_warnings and not validation_dto.warning_counts
    ):
        validation_dto = None
        v_internal = "unavailable"
        v_safe = False
    else:
        if v_internal != "unavailable":
            statuses_collected.append(v_status)
        if not v_safe:
            validation_dto = None
    v_external = _to_external_source(v_internal, v_safe)

    # ── 7) indicator_chart (P1-③: read-time macro context 합성, lineage 독립)
    # indicator_chart 는 evidence/lineage 가드와 무관하게 period 범위에 대한
    # macro_service.build_macro_timeseries 를 호출하여 합성한다.
    # client 노출 조건: caller (report router) 가 approved final 검증 후 호출.
    indicator = _build_indicator_chart(period)
    if indicator.series:
        indicator_internal: InternalEnrichmentSource = "macro_timeseries"
        indicator_external: IndicatorChartSource = "macro_timeseries"
    else:
        indicator_internal = "unavailable"
        indicator_external = "unavailable"

    # ── 8) 전체 정합성 + 사유 메시지 (raw — admin/debug 전용, client 미노출)
    overall_status = _aggregate_consistency(statuses_collected)
    reason: str | None = None
    if overall_status == "matched_by_id":
        reason = (
            f"approved_debate_run_id={approved_run_id} == "
            f"draft/jsonl debate_run_id (ID strict 일치)"
        )
    elif overall_status == "id_mismatch":
        if approved_run_id:
            reason = (
                f"approved_debate_run_id={approved_run_id} 와 일치하는 "
                f"draft/jsonl debate_run_id 없음 — timestamp fallback 금지 → 차단"
            )
        else:
            reason = "id_mismatch (approved_debate_run_id 부재 + 다른 위험 신호)"
    elif approved_at is None and not approved_run_id:
        reason = (
            "final.approved_at 및 approved_debate_run_id 누락 — "
            "lineage 비교 불가 (모든 enrichment unavailable)"
        )
        overall_status = "unverifiable"
    elif overall_status == "newer_than_final":
        reason = (
            f"draft/jsonl timestamp 가 approved_at({approved_at.isoformat()}) "
            f"보다 늦음 — 승인본 lineage 불일치 → client 노출 차단"
        )
    elif overall_status == "unverifiable":
        if draft_payload and draft_ts is None:
            reason = (
                "draft.json 에서 generated_at/debated_at/updated_at/created_at "
                "확인 불가 → client unavailable"
            )
        else:
            reason = "lineage timestamp 비교 불가"
    elif overall_status == "older_than_or_equal_final" and draft_ts is not None:
        reason = (
            f"draft.{draft_ts_key}={draft_ts.isoformat()} "
            f"<= approved_at={approved_at.isoformat()} (legacy timestamp 일치)"
        )

    return InternalReportEnrichmentDTO(
        evidence_annotations=ea_dtos,
        evidence_annotations_source=ea_external,
        evidence_annotations_internal_source=ea_internal,
        related_news=rn_dtos,
        related_news_source=rn_external,
        related_news_internal_source=rn_internal,
        evidence_quality=quality_dto,
        evidence_quality_source=q_external,
        evidence_quality_internal_source=q_internal,
        validation_summary=validation_dto,
        validation_summary_source=v_external,
        validation_summary_internal_source=v_internal,
        indicator_chart=indicator,
        indicator_chart_source=indicator_external,
        indicator_chart_internal_source=indicator_internal,
        source_consistency_status=overall_status,
        source_consistency_reason=reason,
    )


# ──────────────────────────────────────────────────────────────────────────
# Public wrappers (외부 service 가 호출하는 경계)
# ──────────────────────────────────────────────────────────────────────────

def build_internal_report_enrichment(
    final_payload: dict,
    period: str,
    fund_code: str,
) -> InternalReportEnrichmentDTO:
    """admin/debug 진단용 public wrapper.

    내부 helper `_build_enrichment` 를 그대로 호출하되 외부 service (admin_service)
    가 private 심볼을 직접 참조하지 않도록 경계를 명확히 둔다. client 응답에는
    이 모델이 직접 직렬화되지 않으며, `_to_client_enrichment` 변환만 client 경로에
    노출된다.
    """
    return _build_enrichment(final_payload, period, fund_code)


# ──────────────────────────────────────────────────────────────────────────
# Client-facing enrichment 변환 (internal_source / raw reason 제거)
# ──────────────────────────────────────────────────────────────────────────

# 살균된 client note 매핑. internal 파일명 / draft / jsonl 같은 용어 미포함.
_CLIENT_NOTE_BY_STATUS: dict[SourceConsistencyStatus, str | None] = {
    "matched_by_id": "승인본과 연결된 근거 데이터입니다.",
    "id_mismatch": (
        "승인본과 연결된 근거 데이터가 아니므로 본 화면에는 노출되지 않습니다."
    ),
    "matched": None,
    "older_than_or_equal_final": None,
    "newer_than_final": (
        "근거 데이터가 승인 시점 이후에 생성되어 본 화면에는 노출되지 않습니다."
    ),
    "unverifiable": (
        "승인본과의 연결 여부를 확인할 수 없어 근거 데이터는 노출되지 않습니다."
    ),
    "unavailable": "승인본과 연결된 근거 데이터가 없습니다.",
}


def _to_client_enrichment(
    internal: InternalReportEnrichmentDTO,
) -> ClientReportEnrichmentDTO:
    """Internal 모델 → Client 모델 변환.

    제외 필드: *_internal_source, source_consistency_reason
    추가 필드: source_consistency_note (status별 살균된 한 줄 안내)
    """
    note = _CLIENT_NOTE_BY_STATUS.get(internal.source_consistency_status)
    return ClientReportEnrichmentDTO(
        evidence_annotations=internal.evidence_annotations,
        evidence_annotations_source=internal.evidence_annotations_source,
        related_news=internal.related_news,
        related_news_source=internal.related_news_source,
        evidence_quality=internal.evidence_quality,
        evidence_quality_source=internal.evidence_quality_source,
        validation_summary=internal.validation_summary,
        validation_summary_source=internal.validation_summary_source,
        indicator_chart=internal.indicator_chart,
        indicator_chart_source=internal.indicator_chart_source,
        source_consistency_status=internal.source_consistency_status,
        source_consistency_note=note,
    )


def _make_meta(approved_at: datetime | None) -> BaseMeta:
    as_of = None
    if isinstance(approved_at, datetime):
        as_of = approved_at.date()
    elif isinstance(approved_at, str):
        try:
            as_of = datetime.fromisoformat(approved_at).date()
        except ValueError:
            as_of = None
    return BaseMeta(
        as_of_date=as_of,
        source="db",
        sources=[SourceBreakdown(component="report_store", kind="db")],
        is_fallback=False,
        warnings=[],
        generated_at=datetime.now(timezone.utc),
    )


# ──────────────────────────────────────────────────────────────────────────
# Build entry points
# ──────────────────────────────────────────────────────────────────────────

def _resolve_market_period(
    fund_period: str,
    fund_final_payload: dict,
) -> tuple[str, bool]:
    """펀드 final 이 참조할 시장 debate period 결정.

    우선순위:
      1) fund draft 의 `market_debate_period` 키 (정상 매칭 키)
      2) fund final 의 `market_debate_period` 키 (있을 경우)
      3) fund report period (fallback)

    반환: (market_period, fallback_used).
    """
    draft_payload = rsg.load_draft(fund_period, fund_final_payload.get("fund_code") or "") or {}
    for src in (draft_payload, fund_final_payload):
        v = src.get("market_debate_period")
        if isinstance(v, str) and v.strip() and rsg.is_valid_period(v.strip()):
            # 명시 키 사용 → fallback=False (실제로 다른 기간을 가리킬 수도 있음)
            return v.strip(), False
    # 명시 키 없음 → fund period 를 그대로 fallback 사용
    return fund_period, True


def _build_linked_market_enrichment(
    fund_period: str,
    fund_final_payload: dict,
) -> LinkedMarketEnrichmentDTO:
    """펀드 report 응답에 결합할 시장 enrichment fan-out (P3).

    펀드 lineage 와 분리된 시장 lineage 만으로 검증한다. 시장 final 이
    부재/미승인이거나 lineage 가 unsafe 면 unavailable + 빈 list.

    indicator_chart 는 시장 final 이 승인된 경우에 한해 합성한다 (lineage
    독립이지만 노출 게이트는 시장 final 승인 여부).
    """
    market_period, fallback_used = _resolve_market_period(fund_period, fund_final_payload)

    market_payload = rsg.load_final(market_period, _MARKET_FUND_CODE)
    if not market_payload or not market_payload.get("approved"):
        return LinkedMarketEnrichmentDTO(
            market_period=market_period,
            market_period_fallback=fallback_used,
            source_consistency_status="unavailable",
            source_consistency_note="참조할 시장 승인본이 없습니다.",
        )

    internal = _build_enrichment(market_payload, market_period, _MARKET_FUND_CODE)
    note = _CLIENT_NOTE_BY_STATUS.get(internal.source_consistency_status)
    return LinkedMarketEnrichmentDTO(
        market_period=market_period,
        market_period_fallback=fallback_used,
        evidence_annotations=internal.evidence_annotations,
        evidence_annotations_source=internal.evidence_annotations_source,
        related_news=internal.related_news,
        related_news_source=internal.related_news_source,
        indicator_chart=internal.indicator_chart,
        indicator_chart_source=internal.indicator_chart_source,
        source_consistency_status=internal.source_consistency_status,
        source_consistency_note=note,
    )


def _build_report(period: str, fund_code: str) -> ReportFinalResponseDTO:
    """공통 빌더: load_final → approved 검증 → DTO.

    펀드 report 는 추가로 동일 기간 시장 debate enrichment 를 fan-out 결합한다
    (P3, market_enrichment). 시장 코멘트 자체 응답에는 채우지 않는다.
    """
    payload = rsg.load_final(period, fund_code)
    if not payload:
        raise HTTPException(
            status_code=404,
            detail={"code": "REPORT_NOT_FOUND",
                    "message": f"{fund_code}@{period}"},
        )
    if not payload.get("approved"):
        # final.json은 있으나 approved=false → 미노출
        raise HTTPException(
            status_code=404,
            detail={"code": "REPORT_NOT_APPROVED",
                    "message": f"{fund_code}@{period}"},
        )

    dto = _to_dto(payload, period, fund_code)
    internal_enrichment = _build_enrichment(payload, period, fund_code)
    dto.enrichment = _to_client_enrichment(internal_enrichment)
    if fund_code != _MARKET_FUND_CODE:
        dto.market_enrichment = _build_linked_market_enrichment(period, payload)
    return ReportFinalResponseDTO(
        meta=_make_meta(payload.get("approved_at")),
        data=dto,
    )


def build_market_report(period: str) -> ReportFinalResponseDTO:
    p = _validate_period(period)
    return _build_report(p, _MARKET_FUND_CODE)


def build_fund_report(period: str, fund_code: str) -> ReportFinalResponseDTO:
    p = _validate_period(period)
    fc = _validate_fund(fund_code)
    return _build_report(p, fc)


# ──────────────────────────────────────────────────────────────────────────
# Approved periods listing
# ──────────────────────────────────────────────────────────────────────────

def _list_approved_periods(fund_code: str) -> list[str]:
    """fund_code(_market 포함)의 approved=true final.json 이 존재하는 기간 목록.

    report_store.list_period_dirs() 로 모든 기간 디렉터리를 스캔 후,
    각 기간에서 load_final → approved=true 인 것만 추림.
    정렬: 내림차순 (rsg.list_period_dirs 가 이미 desc 반환).
    """
    out: list[str] = []
    for period in rsg.list_period_dirs():
        payload = rsg.load_final(period, fund_code)
        if payload and payload.get("approved"):
            out.append(period)
    return out


def build_market_approved_periods() -> ReportApprovedPeriodsResponseDTO:
    periods = _list_approved_periods(_MARKET_FUND_CODE)
    return ReportApprovedPeriodsResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source="db",
            sources=[SourceBreakdown(component="report_store", kind="db")],
            is_fallback=False,
            warnings=[],
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=_MARKET_FUND_CODE,
        periods=periods,
    )


def build_fund_approved_periods(fund_code: str) -> ReportApprovedPeriodsResponseDTO:
    fc = _validate_fund(fund_code)
    periods = _list_approved_periods(fc)
    return ReportApprovedPeriodsResponseDTO(
        meta=BaseMeta(
            as_of_date=None,
            source="db",
            sources=[SourceBreakdown(component="report_store", kind="db")],
            is_fallback=False,
            warnings=[],
            generated_at=datetime.now(timezone.utc),
        ),
        fund_code=fc,
        periods=periods,
    )
