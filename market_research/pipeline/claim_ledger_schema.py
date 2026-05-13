# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-β) — promotion ledger row preview schema.

R9-A.2 의 `_promotion_quality.jsonl` 을 확장한 정식 schema (24 필드).
**gitignored 유지** — Commit 3 단계에서는 실 append 0 (preview row 만 반환).

기존 R9-A.1 row 는 11 필드 (cost_usd / write_* / status 미포함). 본 schema 의
신규 필드는 R9-A.4 row 에만 채움 — `compute_monthly_cost_usd` filter 가
source/extractor_version 기준이라 R9-A.1 row 영향 0.

invariant:
  - file write 0
  - ledger read 는 `_promotion_quality.jsonl` 만 (없으면 graceful → cost 0)
  - import 시점 비용 0 (JSONL 은 호출 시점에 한 번만 읽음)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from market_research.analyze.claim_store import PROMOTION_LEDGER_PATH


# Commit 3 — 24 legacy fields. C3 row 의 read backward compat 검증 용도로 보존.
# C4 신규 row 는 LEDGER_ROW_FIELDS (32 fields) 를 사용.
LEDGER_ROW_FIELDS_C3: tuple[str, ...] = (
    "ts",
    "period",
    "source",
    "extractor_version",
    "input_count",
    "valid_claim_count",
    "invalid_claim_count",
    "promoted_count",
    "skipped_count",
    "promotion_rate",
    "rule",
    "rule_breakdown",
    "skip_reasons",
    "cost_usd",
    "monthly_cost_usd_so_far",
    "dry_run",
    "write_canonical",
    "write_wiki",
    "write_ledger",
    "status",
    "abort_reason",
    "warnings",
    "out_of_band_override",
    "target_suffix",
)

# Commit 4 — 32 fields. C3 의 24 fields 확장 (기존 키 변경 0, 신규 8 키만 추가).
# workorder r9a4_commit4_workorder.md §6 / §8 schema. dict 순서가 row JSON 출력 순서.
LEDGER_ROW_FIELDS_C4_INITIAL: tuple[str, ...] = LEDGER_ROW_FIELDS_C3 + (
    # write gate monitoring
    "write_allowed",                    # 최종 write 진입 여부
    "write_block_reason",               # 차단 사유 (None | enum string)
    "allow_out_of_band",                # flag echo
    "write_claims",                     # flag echo (write_canonical=wiki=ledger 통합값)
    # cost / capacity monitoring
    "monthly_cost_before",              # 호출 전 누적 cost (= monthly_cost_usd_so_far 와 동일 의미, drift 추적용 dup)
    "monthly_cost_after_estimate",      # before + est_cost
    # plan monitoring
    "candidate_count",                  # plan input_count (valid claims)
    "canonical_existing_conflict_count",  # plan.merge_conflicts 길이
)

# Commit 4.1 — 33 fields. isolated_write 추가 (target_suffix 분리 표시).
# C4 initial 32 → C4.1 33 으로 확장 — backward compat: C3 24/C4 32 row 도
# validate_ledger_row_preview(allow_legacy_c3=True) 로 graceful read 가능.
LEDGER_ROW_FIELDS: tuple[str, ...] = LEDGER_ROW_FIELDS_C4_INITIAL + (
    "isolated_write",                   # target_suffix 가 None 이 아닐 때 True
)

# R9-A.22B — Group monitoring traceability optional fields.
# 본 5 필드는 **strict required set 에 포함되지 않는다** (LEDGER_ROW_FIELDS 미수정).
# build_ledger_row_preview 에 명시 인자로 전달된 경우에만 row dict 에 추가됨 —
# default 호출 시 33필드 출력이 보존되어 기존 소비자 / 회귀 테스트 무영향.
LEDGER_ROW_OPTIONAL_FIELDS_R9A22: tuple[str, ...] = (
    "group_monitoring_summary_path",     # str — Step 2.8 / promotion_monthly_summary 산출 경로
    "related_group_ids",                 # list[str] — 예: ["group:2026-04:cfee0ff342"]
    "linked_wiki_claim_ids",             # list[str] — wiki anchor 의 hash10 (예: ["de1729b413"])
    "monitoring_mode",                   # "single_batch" | "multi_run"
    "stable_candidate_counts",           # dict (total_groups / stable / strong / within_run_dup)
)

# R9-A.19 monitoring_mode allowed values — invalid 값은 validate 에서 errors.
MONITORING_MODE_VALUES: frozenset[str] = frozenset({"single_batch", "multi_run"})

# stable_candidate_counts dict 의 권장 sub-key (참고용, 강제 X)
STABLE_CANDIDATE_COUNT_KEYS: tuple[str, ...] = (
    "total_groups",
    "stable_candidates",
    "strong_stable_candidates",
    "within_run_duplicate_count",
)

# Monthly cap — workorder §5 D-4. Commit 4 에서 CLI override 가능 예정.
MONTHLY_CAP_USD: float = 1.0


def _to_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _to_str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    return str(v)


def compute_monthly_cost_usd(
    period: str,
    *,
    source: str = "daily_update_r9a4",
    extractor_version: str = "r9a.4-haiku",
    ledger_path: str | Path | None = None,
) -> float:
    """동일 month + source + extractor_version filter row 들의 cost_usd 합산.

    Parameters
    ----------
    period : "YYYY-MM" 또는 "YYYY-MM-DD" — 앞 7자가 month key 로 사용됨.
    source : 합산 대상 source tag (default 'daily_update_r9a4'). manual_pilot
              계열은 자연 제외 (R9-A.1 row 영향 0).
    extractor_version : default 'r9a.4-haiku'.
    ledger_path : test override. None 이면 PROMOTION_LEDGER_PATH.

    파일 결손 / parse 실패 / period 비정상 모두 graceful → 0.0 반환.
    """
    if not isinstance(period, str) or not period:
        return 0.0
    month_key = period[:7]

    p = Path(ledger_path) if ledger_path else PROMOTION_LEDGER_PATH
    if not p.exists():
        return 0.0

    total = 0.0
    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                row_period = str(row.get("period", ""))
                if not row_period.startswith(month_key):
                    continue
                if str(row.get("source", "")) != source:
                    continue
                if str(row.get("extractor_version", "")) != extractor_version:
                    continue
                total += _to_float(row.get("cost_usd"), 0.0)
    except OSError:
        return 0.0
    return round(total, 6)


def build_ledger_row_preview(
    *,
    period: str,
    source: str = "daily_update_r9a4",
    extractor_version: str = "r9a.4-haiku",
    input_count: int = 0,
    valid_claim_count: int = 0,
    invalid_claim_count: int = 0,
    promoted_count: int = 0,
    skipped_count: int = 0,
    promotion_rate: float = 0.0,
    rule: str = "auto",
    rule_breakdown: dict | None = None,
    skip_reasons: dict | None = None,
    cost_usd: float = 0.0,
    monthly_cost_usd_so_far: float = 0.0,
    dry_run: bool = True,
    write_canonical: bool = False,
    write_wiki: bool = False,
    write_ledger: bool = False,
    status: str = "ok_plan_ready",
    abort_reason: str | None = None,
    warnings: list | None = None,
    out_of_band_override: bool = False,
    target_suffix: str | None = None,
    ts: str | None = None,
    # Commit 4 신규 8 fields
    write_allowed: bool = False,
    write_block_reason: str | None = None,
    allow_out_of_band: bool = False,
    write_claims: bool = False,
    monthly_cost_before: float | None = None,
    monthly_cost_after_estimate: float | None = None,
    candidate_count: int = 0,
    canonical_existing_conflict_count: int = 0,
    # Commit 4.1 — target_suffix isolation 표시
    isolated_write: bool | None = None,
    # R9-A.22B — Group monitoring traceability optional fields.
    # 모두 default None — 명시 인자 전달이 없으면 row dict 에 포함하지 않음
    # (33필드 default contract 보존).
    group_monitoring_summary_path: str | Path | None = None,
    related_group_ids: list[str] | None = None,
    linked_wiki_claim_ids: list[str] | None = None,
    monitoring_mode: str | None = None,
    stable_candidate_counts: dict | None = None,
) -> dict[str, Any]:
    """Commit 3 단계의 ledger row preview.

    실 append 0 — 호출 측은 `step_claim_extract` 의 `would_save` 안에서
    이 row 를 metadata 로 reference 만. Commit 4 에서 `append_promotion_ledger`
    가 본 row 를 그대로 받아 write.

    type coercion 은 보수적으로 — int/float/str 타입 안정성 보장 (jsonl
    serialization 회귀 방지).

    R9-A.22B 옵셔널 group monitoring traceability:
      - `group_monitoring_summary_path` / `related_group_ids` /
        `linked_wiki_claim_ids` / `monitoring_mode` /
        `stable_candidate_counts` 5종
      - 모두 default None — 미전달 시 row 에 키 자체가 없음 (33필드 그대로)
      - 전달 시 row 에 키 추가 (소비자는 unknown key 에 graceful 해야 함 —
        json.dumps sort_keys 출력이므로 마지막 정렬 위치)
    """
    if ts is None:
        ts = datetime.now().isoformat(timespec="seconds")

    # monthly_cost_before default = monthly_cost_usd_so_far (drift 추적 dup).
    _before = (
        _to_float(monthly_cost_before)
        if monthly_cost_before is not None
        else _to_float(monthly_cost_usd_so_far)
    )
    _after = (
        _to_float(monthly_cost_after_estimate)
        if monthly_cost_after_estimate is not None
        else _to_float(_before + cost_usd)
    )

    row: dict[str, Any] = {
        "ts": ts,
        "period": str(period or ""),
        "source": str(source or ""),
        "extractor_version": str(extractor_version or ""),
        "input_count": _to_int(input_count),
        "valid_claim_count": _to_int(valid_claim_count),
        "invalid_claim_count": _to_int(invalid_claim_count),
        "promoted_count": _to_int(promoted_count),
        "skipped_count": _to_int(skipped_count),
        "promotion_rate": round(_to_float(promotion_rate), 2),
        "rule": str(rule or "auto"),
        "rule_breakdown": dict(rule_breakdown or {}),
        "skip_reasons": dict(skip_reasons or {}),
        "cost_usd": round(_to_float(cost_usd), 6),
        "monthly_cost_usd_so_far": round(_to_float(monthly_cost_usd_so_far), 6),
        "dry_run": bool(dry_run),
        "write_canonical": bool(write_canonical),
        "write_wiki": bool(write_wiki),
        "write_ledger": bool(write_ledger),
        "status": str(status or ""),
        "abort_reason": _to_str_or_none(abort_reason),
        "warnings": list(warnings or []),
        "out_of_band_override": bool(out_of_band_override),
        "target_suffix": _to_str_or_none(target_suffix),
        # Commit 4 신규 8
        "write_allowed": bool(write_allowed),
        "write_block_reason": _to_str_or_none(write_block_reason),
        "allow_out_of_band": bool(allow_out_of_band),
        "write_claims": bool(write_claims),
        "monthly_cost_before": round(_before, 6),
        "monthly_cost_after_estimate": round(_after, 6),
        "candidate_count": _to_int(candidate_count),
        "canonical_existing_conflict_count": _to_int(
            canonical_existing_conflict_count),
        # Commit 4.1 — target_suffix 가 None 이 아니면 자동 True (호출 측 echo
        # 없이도 도출 가능). 명시 호출자 우선.
        "isolated_write": (
            bool(isolated_write) if isolated_write is not None
            else bool(target_suffix)
        ),
    }

    # R9-A.22B — Optional group monitoring traceability.
    # 명시 인자가 None 이 아닐 때만 row 에 키 추가. None 만 받은 호출은 33필드
    # default 그대로 (LEDGER_ROW_FIELDS 회귀 검증 통과 보장).
    if group_monitoring_summary_path is not None:
        row["group_monitoring_summary_path"] = str(group_monitoring_summary_path)
    if related_group_ids is not None:
        row["related_group_ids"] = [str(x) for x in related_group_ids]
    if linked_wiki_claim_ids is not None:
        row["linked_wiki_claim_ids"] = [str(x) for x in linked_wiki_claim_ids]
    if monitoring_mode is not None:
        row["monitoring_mode"] = str(monitoring_mode)
    if stable_candidate_counts is not None:
        # 권장 sub-key 는 int coercion, 그 외는 원형 보존 (소비자 확장 여지).
        coerced: dict[str, Any] = dict(stable_candidate_counts)
        for k in STABLE_CANDIDATE_COUNT_KEYS:
            if k in coerced:
                coerced[k] = _to_int(coerced[k])
        row["stable_candidate_counts"] = coerced

    return row


def validate_ledger_row_preview(
    row: dict,
    *,
    allow_legacy_c3: bool = False,
) -> list[str]:
    """필수 필드 누락 / 타입 오류 → 오류 메시지 list 반환 (빈 list = 정상).

    Parameters
    ----------
    row : dict
        검증 대상 row.
    allow_legacy_c3 : bool
        True 이면 Commit 3 의 24필드 schema 만 충족해도 valid 로 판정.
        Commit 4 신규 8필드 누락은 errors 가 아닌 통과.
        gitignored ledger 의 backward compat read 검증 용도.
        default False — Commit 4 신규 row 는 32필드 모두 채워야 valid.

    Commit 4 신규: backward compat 모드 추가.
    """
    errors: list[str] = []
    if not isinstance(row, dict):
        return ["row_not_dict"]

    required = LEDGER_ROW_FIELDS_C3 if allow_legacy_c3 else LEDGER_ROW_FIELDS
    for field in required:
        if field not in row:
            errors.append(f"missing_field:{field}")

    # type sanity — 존재하는 필드만 검사 (graceful)
    for f in ("input_count", "valid_claim_count", "invalid_claim_count",
              "promoted_count", "skipped_count", "candidate_count",
              "canonical_existing_conflict_count"):
        if f in row and not isinstance(row[f], int):
            errors.append(f"type_error:{f}_not_int")
    for f in ("cost_usd", "monthly_cost_usd_so_far", "promotion_rate",
              "monthly_cost_before", "monthly_cost_after_estimate"):
        if f in row and not isinstance(row[f], (int, float)):
            errors.append(f"type_error:{f}_not_number")
    for f in ("dry_run", "write_canonical", "write_wiki", "write_ledger",
              "out_of_band_override", "write_allowed", "allow_out_of_band",
              "write_claims", "isolated_write"):
        if f in row and not isinstance(row[f], bool):
            errors.append(f"type_error:{f}_not_bool")

    # R9-A.22B — optional traceability fields, type-check only when present.
    if "group_monitoring_summary_path" in row:
        if not isinstance(row["group_monitoring_summary_path"], str):
            errors.append(
                "type_error:group_monitoring_summary_path_not_str")
    if "related_group_ids" in row:
        v = row["related_group_ids"]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            errors.append("type_error:related_group_ids_not_list_str")
    if "linked_wiki_claim_ids" in row:
        v = row["linked_wiki_claim_ids"]
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            errors.append("type_error:linked_wiki_claim_ids_not_list_str")
    if "monitoring_mode" in row:
        v = row["monitoring_mode"]
        if not isinstance(v, str):
            errors.append("type_error:monitoring_mode_not_str")
        elif v not in MONITORING_MODE_VALUES:
            errors.append(f"value_error:monitoring_mode_invalid:{v}")
    if "stable_candidate_counts" in row:
        if not isinstance(row["stable_candidate_counts"], dict):
            errors.append("type_error:stable_candidate_counts_not_dict")

    return errors
