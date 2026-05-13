# -*- coding: utf-8 -*-
"""R9-A.4 Step 2.7 — claim extractor 정기 batch (Commit 3 확장).

본 모듈은 R9-A.4 mini-spec (`docs/r9a4_minispec.md`) 의 진입점.
Commit 1 (skeleton) → Commit 2 (runner 연결, dry-run) → **Commit 3 (failure
matrix + monthly cap + promotion plan + ledger preview)** → Commit 4
(CLI flag + 실 write).

Commit 3 단계의 책임:
  - failure handling matrix 10 case 분기 (§4 workorder)
  - monthly cost cap ($1) pre-abort (D-4)
  - promotion plan 생성 (`claim_promotion_plan.build_promotion_plan`)
  - ledger row preview (claim_ledger_schema)
  - would_save 강화 (canonical/wiki/ledger 별 detail)
  - dry_run_debug_path 옵션 (D-3 — debug/claims/ 만 허용)

Invariants (Commit 3):
  - file write 0 — canonical/wiki/ledger 어디에도 안 씀
  - daily_update 운영 default 영향 0 (ENABLE_CLAIM_EXTRACTION=False)
  - LLM 호출은 runner 가 1회 (evidence 있고 cost cap 통과 시 한 번)
  - failure 10 유형 모두 graceful (raise 0, D-6)

Commit 4 책임 (Commit 3 미포함):
  - CLI flag (--dry-run-claim / --force-claim-extract / --target-suffix /
    --allow-out-of-band)
  - canonical store / wiki / ledger 실 write
  - target_suffix 기반 file path 분리 실 적용
  - out-of-band guard 실 abort 분기
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from market_research.pipeline.claim_ledger_schema import (
    MONTHLY_CAP_USD,
    build_ledger_row_preview,
    compute_monthly_cost_usd,
)
from market_research.pipeline.claim_promotion_plan import (
    DEFAULT_MERGE_POLICY,
    build_promotion_plan,
)


# ──────────────────────────────────────────────────────────────────
# Feature flag (default OFF)
# ──────────────────────────────────────────────────────────────────
# daily_update 운영 default 에서 Step 2.7 가 no-op 임을 보장.
# True 로 켜도 본 모듈은 file write 0 (Commit 3 invariant).
# Commit 4 에서 CLI flag 와 함께 정식 활성화.
ENABLE_CLAIM_EXTRACTION: bool = False


# ──────────────────────────────────────────────────────────────────
# Status 상수 (Commit 3 매트릭스)
# ──────────────────────────────────────────────────────────────────

# Commit 1+2 호환 — 기존 외부 import 안정성 유지.
STATUS_DISABLED = "disabled"
STATUS_SKELETON = "skeleton_no_op"

# Commit 3 신규 — failure matrix 10 case 매핑.
STATUS_OK_PLAN_READY = "ok_plan_ready"
STATUS_RUNNER_ABORTED = "runner_aborted"             # F-1, F-2
STATUS_PARTIAL_EXTRACTION = "partial_extraction"     # F-3, F-8
STATUS_NO_VALID_CLAIMS = "no_valid_claims"           # F-4
STATUS_PROMOTION_ZERO = "promotion_zero"             # F-5
STATUS_PROMOTION_OUT_OF_BAND = "promotion_out_of_band"   # F-6
STATUS_COST_CAP_PRE_ABORT = "cost_cap_pre_abort"     # F-7 (runner 측)
STATUS_COST_CAP_MONTHLY_PRE_ABORT = "cost_cap_monthly_pre_abort"  # Commit 3 신규
STATUS_PERIOD_MISMATCH = "period_mismatch"           # F-9
STATUS_MERGE_CONFLICT_PREVIEW = "merge_conflict_preview"  # F-10


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

_ABORT_REASON_TO_STATUS: dict[str, tuple[str, str]] = {
    "llm_api_failure": (STATUS_RUNNER_ABORTED, "llm_api_failure"),
    "json_parse_failed": (STATUS_RUNNER_ABORTED, "json_parse_failed"),
    "cost_cap_exceeded_estimate": (
        STATUS_COST_CAP_PRE_ABORT, "cost_cap_exceeded_estimate",
    ),
}


def _validate_debug_path(p: str | Path | None) -> Path | None:
    """D-3 — `debug/claims/` 이하만 허용. 그 외 경로 → ValueError.

    None 이면 dump 미진행 → None 반환 (정상).
    """
    if p is None:
        return None
    pth = Path(p)
    parts = pth.parts
    try:
        idx = parts.index("debug")
    except ValueError:
        raise ValueError(
            f"dry_run_debug_path 는 debug/claims/ 이하만 허용 "
            f"(받은 경로: {pth})"
        )
    tail = parts[idx:]
    if len(tail) < 2 or tail[1] != "claims":
        raise ValueError(
            f"dry_run_debug_path 는 debug/claims/ 이하만 허용 "
            f"(받은 경로: {pth})"
        )
    if ".." in parts:
        raise ValueError(f"dry_run_debug_path 경로 traversal 금지: {pth}")
    return pth


def _canonical_target_path(period: str, target_suffix: str | None) -> str:
    base = f"market_research/data/claims/{period}"
    if target_suffix:
        return f"{base}.{target_suffix}.json"
    return f"{base}.json"


# ──────────────────────────────────────────────────────────────────
# C4-β — Write gate (G-11/G-12/G-13)
# ──────────────────────────────────────────────────────────────────

def _evaluate_write_gate(
    *,
    status: str,
    plan: dict | None,
    invalid_count: int,
    actual_cost: float,
    cost_cap_usd: float,
    write_canonical: bool,
    write_wiki: bool,
    write_ledger: bool,
    allow_out_of_band: bool,
    target_suffix: str | None,
) -> tuple[bool, str | None]:
    """workorder §5 — G-1~G-13 다단 검증. Returns (write_allowed, reason).

    G-11 : `--write-claims` (3종 모두 True)
    G-12 : out_of_band=True 면 allow_out_of_band 필요
    G-13 : target_suffix 미지정 시 운영 file 덮어쓰기 차단 (C4-Q4=B)

    failure status 들은 자동으로 write_block_reason 에 매핑 (G-3~G-10).
    """
    write_claims_flag = bool(write_canonical and write_wiki and write_ledger)

    # G-11 — flag 미지정 시 항상 dry-run
    if not write_claims_flag:
        return False, "default_dry_run"

    # Status-driven blocks (G-3~G-10)
    if status == STATUS_COST_CAP_MONTHLY_PRE_ABORT:
        return False, "monthly_cap_exceeded"
    if status == STATUS_COST_CAP_PRE_ABORT:
        return False, "cost_cap_pre_estimate"
    if status == STATUS_RUNNER_ABORTED:
        return False, "runner_aborted"
    if status == STATUS_NO_VALID_CLAIMS:
        return False, "no_valid_claims"
    if status == STATUS_PERIOD_MISMATCH:
        return False, "period_mismatch"
    if status == STATUS_MERGE_CONFLICT_PREVIEW:
        return False, "merge_conflict_present"
    if status == STATUS_PROMOTION_ZERO:
        return False, "promotion_zero"
    if status == STATUS_PARTIAL_EXTRACTION:
        # F-3 (invalid > 0) 또는 F-8 (cost cap actual). 안전망 — write 0.
        if invalid_count > 0:
            return False, "invalid_present"
        if actual_cost > cost_cap_usd:
            return False, "cost_cap_exceeded_actual"
        return False, "partial_extraction"

    # G-12 — out_of_band 기본 차단
    if status == STATUS_PROMOTION_OUT_OF_BAND:
        if not allow_out_of_band:
            return False, "out_of_band_default_block"
        # else: allow flag 명시 → 다음 gate 로

    # G-13 — target_suffix 미지정 시 운영 file 덮어쓰기 차단 (Q4=B)
    if target_suffix is None:
        return False, "missing_target_suffix"

    # 통과 — STATUS_OK_PLAN_READY 또는 (STATUS_PROMOTION_OUT_OF_BAND + allow)
    return True, None


def _period_mismatch_ids(claims: list[dict], period: str) -> list[str]:
    out: list[str] = []
    for c in claims or []:
        if not isinstance(c, dict):
            continue
        cp = c.get("period")
        if cp != period:
            cid = c.get("claim_id") or "(no id)"
            out.append(cid)
    return out


def _build_would_save(
    *,
    period: str,
    target_suffix: str | None,
    plan: dict | None,
    valid_count: int,
    write_canonical: bool,
    write_wiki: bool,
    write_ledger: bool,
    canonical_existing_count: int,
    ledger_row_preview: dict | None,
) -> list[dict]:
    """workorder §9 구조 — canonical/wiki/ledger 별 detail dict.

    Commit 3 단계 — write_* 가 True 여도 enabled_in_this_commit=False.
    Commit 4 에서 True 로 전환되고 실 write 함수가 본 dict 를 consume.
    """
    if not (write_canonical or write_wiki or write_ledger):
        return []

    promoted_count = int((plan or {}).get("promoted_count", 0) or 0)
    skipped_count = int((plan or {}).get("skipped_count", 0) or 0)
    would_pages: list[dict] = []
    if plan:
        for w in plan.get("would_write", []):
            if isinstance(w, dict) and w.get("kind") == "wiki_08_claims":
                cid = w.get("claim_id") or ""
                page = w.get("wiki_page") or ""
                hash10 = (cid.rsplit(":", 1)[-1] if ":" in cid else cid)
                would_pages.append({
                    "hash10": hash10,
                    "filename": page,
                })

    return [
        {
            "kind": "canonical_store",
            "path": _canonical_target_path(period, target_suffix),
            "enabled_in_this_commit": False,
            "merge_policy": (plan or {}).get(
                "merge_policy", DEFAULT_MERGE_POLICY
            ),
            "existing_claim_count": canonical_existing_count,
            "would_add_count": promoted_count,
            "would_skip_count": skipped_count,
            "would_overwrite_count": 0,
        },
        {
            "kind": "wiki_08_claims",
            "path": "market_research/data/wiki/08_Claims/",
            "enabled_in_this_commit": False,
            "would_create_pages": would_pages,
            "would_skip_pages_count": skipped_count,
        },
        {
            "kind": "promotion_ledger",
            "path": "market_research/data/claims/_promotion_quality.jsonl",
            "enabled_in_this_commit": False,
            "would_append_row": ledger_row_preview,
        },
    ]


# ──────────────────────────────────────────────────────────────────
# step_claim_extract (Commit 3 본체)
# ──────────────────────────────────────────────────────────────────

def step_claim_extract(
    period: str,
    *,
    enabled: bool | None = None,
    target_suffix: str | None = None,
    evidence_items: list[dict] | None = None,
    dry_run: bool = True,
    cost_cap_usd: float = 0.5,
    monthly_cap_usd: float = MONTHLY_CAP_USD,
    write_canonical: bool = False,
    write_wiki: bool = False,
    write_ledger: bool = False,
    allow_out_of_band: bool = False,
    dry_run_debug_path: str | Path | None = None,
    write_invalid_dump: bool = False,
    rule: str = "auto",
    force_promote_ids: Iterable[str] = (),
    canonical_existing: list[dict] | None = None,
    ledger_path_override: str | Path | None = None,
    llm_call=None,
    # R9-A.22B — Group monitoring traceability passthrough.
    # 모두 default None — 미전달 시 ledger row 33필드 default 보존.
    group_monitoring_summary_path: str | Path | None = None,
    related_group_ids: list[str] | None = None,
    linked_wiki_claim_ids: list[str] | None = None,
    monitoring_mode: str | None = None,
    stable_candidate_counts: dict | None = None,
) -> dict[str, Any]:
    """daily_update Step 2.7 진입점 (Commit 3).

    Parameters
    ----------
    period : "YYYY-MM"
    enabled : feature flag override. None 이면 ENABLE_CLAIM_EXTRACTION.
    target_suffix : D-2 — replay/smoke 산출물 분리. Commit 3 echo 만.
    evidence_items : refined evidence (memory dict). None/[] 이면 runner 호출 0.
    cost_cap_usd : per-run cap (D-4) — runner 내부 사전 추정 분기에 사용.
    monthly_cap_usd : month 누적 cap (D-4 추가). 본 step 함수 책임.
    dry_run_debug_path : D-3 — debug/claims/ 이하만 허용. None 이면 dump 0.
    write_invalid_dump : C3-Q6 default B — explicit True 일 때만 invalid raw
        dump path 가 would_save 에 반영.
    rule : promotion plan rule selector (default "auto").
    force_promote_ids : Rule C — 강제 promote.
    canonical_existing : merge conflict 비교용 (test inject). None 이면 자동
        로드 (단, Commit 3 단계 graceful — load 실패 시 빈 list).
    ledger_path_override : test override (monthly cap source).
    llm_call : 테스트 / admin override. None 이면 runner default.

    Returns — status dict (Commit 3 확장):
      기존: status / period / enabled / target_suffix / ts / llm_calls /
            writes / notes / extraction / would_save / actually_saved
      신규 (Commit 3):
        + warning_code           : failure matrix warning code
        + monthly_cost_usd_so_far: 누적 cost (ledger)
        + estimated_run_cost_usd : 추정 비용
        + plan                   : promotion plan dict (or None)
        + ledger_row_preview     : 24필드 row preview (or None)
        + period_mismatch_ids    : F-9 검출 결과

    Invariants:
      - daily_update 운영 default 영향 0
      - file write 0 — write_* 모두 무시 (Commit 4+ 에서 정식 활성화)
      - failure 10 유형 graceful (raise 0)
    """
    use_enabled = (
        bool(enabled) if enabled is not None
        else bool(ENABLE_CLAIM_EXTRACTION)
    )
    ts = datetime.now().isoformat(timespec="seconds")

    # dry_run_debug_path 검증은 enabled 무관 — 호출 측 contract 보호 (D-3).
    # ValueError 는 raise 전파 (caller 의 명백한 오류 — daily_update 는 try/except
    # graceful 가드 안에서 호출되므로 daily_update 전체는 여전히 안전).
    _validate_debug_path(dry_run_debug_path)

    base = {
        "period": period,
        "enabled": use_enabled,
        "target_suffix": target_suffix,
        "ts": ts,
        "llm_calls": 0,
        "writes": 0,
        "extraction": None,
        "would_save": [],
        "actually_saved": [],
        "warning_code": None,
        "monthly_cost_usd_so_far": 0.0,
        "estimated_run_cost_usd": 0.0,
        "plan": None,
        "ledger_row_preview": None,
        "period_mismatch_ids": [],
        # Commit 4 monitoring fields
        "write_allowed": False,
        "write_block_reason": None,
        "allow_out_of_band": bool(allow_out_of_band),
        "write_claims": bool(write_canonical and write_wiki and write_ledger),
        "candidate_count": 0,
        "canonical_existing_conflict_count": 0,
    }

    if not use_enabled:
        return {
            **base,
            "status": STATUS_DISABLED,
            "notes": (
                "R9-A.4 Step 2.7 disabled. ENABLE_CLAIM_EXTRACTION=False — "
                "extractor / canonical write 미실행."
            ),
        }

    # enabled=True — Commit 2/3 분기
    if not evidence_items:
        return {
            **base,
            "status": STATUS_SKELETON,
            "notes": (
                "Step 2.7 enabled 이나 evidence_items=None/[] — runner 호출 0. "
                "no_input."
            ),
        }

    # Monthly cap pre-abort (Commit 3 신규, D-4)
    monthly_so_far = compute_monthly_cost_usd(
        period, ledger_path=ledger_path_override,
    )
    try:
        from market_research.analyze.claim_extractor_runner import (
            estimate_pre_call_cost_usd,
            extract_claims,
        )
    except Exception as exc:
        return {
            **base,
            "status": STATUS_SKELETON,
            "notes": f"runner import 실패 (graceful): {exc}",
        }
    est_cost = estimate_pre_call_cost_usd(period, evidence_items)
    base["monthly_cost_usd_so_far"] = round(monthly_so_far, 6)
    base["estimated_run_cost_usd"] = round(est_cost, 6)
    if monthly_so_far + est_cost > monthly_cap_usd:
        ledger_preview = build_ledger_row_preview(
            ts=ts,
            period=period,
            input_count=len(evidence_items),
            valid_claim_count=0,
            invalid_claim_count=0,
            promoted_count=0,
            skipped_count=0,
            promotion_rate=0.0,
            rule=rule,
            rule_breakdown={"A": 0, "B": 0, "C": 0},
            skip_reasons={},
            cost_usd=0.0,
            monthly_cost_usd_so_far=monthly_so_far,
            dry_run=True,
            write_canonical=write_canonical,
            write_wiki=write_wiki,
            write_ledger=write_ledger,
            status=STATUS_COST_CAP_MONTHLY_PRE_ABORT,
            abort_reason="cost_cap_exceeded_monthly",
            warnings=[
                f"monthly_cost_cap_exceeded: "
                f"${monthly_so_far:.4f}+${est_cost:.4f} > ${monthly_cap_usd}"
            ],
            out_of_band_override=False,
            target_suffix=target_suffix,
            write_allowed=False,
            write_block_reason="monthly_cap_exceeded",
            allow_out_of_band=allow_out_of_band,
            write_claims=bool(write_canonical and write_wiki and write_ledger),
            monthly_cost_before=monthly_so_far,
            monthly_cost_after_estimate=monthly_so_far + est_cost,
            candidate_count=0,
            canonical_existing_conflict_count=0,
            # R9-A.22B — group monitoring traceability passthrough
            group_monitoring_summary_path=group_monitoring_summary_path,
            related_group_ids=related_group_ids,
            linked_wiki_claim_ids=linked_wiki_claim_ids,
            monitoring_mode=monitoring_mode,
            stable_candidate_counts=stable_candidate_counts,
        )
        return {
            **base,
            "status": STATUS_COST_CAP_MONTHLY_PRE_ABORT,
            "warning_code": "cost_cap_exceeded_monthly",
            "ledger_row_preview": ledger_preview,
            "write_block_reason": "monthly_cap_exceeded",
            "notes": (
                f"monthly cap pre-abort: ${monthly_so_far:.4f}+"
                f"${est_cost:.4f} > ${monthly_cap_usd}. LLM 호출 0."
            ),
        }

    # Runner 호출 (Commit 2 와 동일)
    try:
        result = extract_claims(
            period=period,
            evidence_items=evidence_items,
            dry_run=True,         # Commit 3: 항상 dry-run (write 0)
            cost_cap_usd=cost_cap_usd,
            llm_call=llm_call,
        )
    except Exception as exc:
        # 정상적으로는 runner 가 graceful — 진입 경로 자체가 실패한 경우.
        return {
            **base,
            "status": STATUS_RUNNER_ABORTED,
            "warning_code": "runner_exception",
            "notes": f"runner 호출 실패 (graceful): {exc}",
        }

    llm_calls = (
        0 if result.get("abort_reason") in
        ("no_evidence", "cost_cap_exceeded_estimate") else 1
    )

    # Failure matrix dispatch — abort_reason 우선
    abort_reason = result.get("abort_reason")
    valid_claims = list(result.get("claims") or [])
    invalid_claims = list(result.get("invalid_claims") or [])
    actual_cost = float(result.get("cost_usd", 0.0) or 0.0)

    if abort_reason in _ABORT_REASON_TO_STATUS:
        status, warning_code = _ABORT_REASON_TO_STATUS[abort_reason]
        plan = None
        _, abort_block_reason = _evaluate_write_gate(
            status=status,
            plan=None,
            invalid_count=len(invalid_claims),
            actual_cost=actual_cost,
            cost_cap_usd=cost_cap_usd,
            write_canonical=write_canonical,
            write_wiki=write_wiki,
            write_ledger=write_ledger,
            allow_out_of_band=allow_out_of_band,
            target_suffix=target_suffix,
        )
        ledger_preview = build_ledger_row_preview(
            ts=ts,
            period=period,
            input_count=len(evidence_items),
            valid_claim_count=0,
            invalid_claim_count=len(invalid_claims),
            promoted_count=0,
            skipped_count=0,
            promotion_rate=0.0,
            rule=rule,
            rule_breakdown={"A": 0, "B": 0, "C": 0},
            skip_reasons={},
            cost_usd=actual_cost,
            monthly_cost_usd_so_far=monthly_so_far,
            dry_run=True,
            write_canonical=write_canonical,
            write_wiki=write_wiki,
            write_ledger=write_ledger,
            status=status,
            abort_reason=abort_reason,
            warnings=list(result.get("warnings") or []),
            out_of_band_override=False,
            target_suffix=target_suffix,
            write_allowed=False,
            write_block_reason=abort_block_reason,
            allow_out_of_band=allow_out_of_band,
            write_claims=bool(write_canonical and write_wiki and write_ledger),
            monthly_cost_before=monthly_so_far,
            monthly_cost_after_estimate=monthly_so_far + actual_cost,
            candidate_count=0,
            canonical_existing_conflict_count=0,
            # R9-A.22B — group monitoring traceability passthrough
            group_monitoring_summary_path=group_monitoring_summary_path,
            related_group_ids=related_group_ids,
            linked_wiki_claim_ids=linked_wiki_claim_ids,
            monitoring_mode=monitoring_mode,
            stable_candidate_counts=stable_candidate_counts,
        )
        return {
            **base,
            "status": status,
            "warning_code": warning_code,
            "llm_calls": llm_calls,
            "extraction": result,
            "plan": plan,
            "ledger_row_preview": ledger_preview,
            "write_block_reason": abort_block_reason,
            "would_save": _build_would_save(
                period=period,
                target_suffix=target_suffix,
                plan=None,
                valid_count=0,
                write_canonical=write_canonical,
                write_wiki=write_wiki,
                write_ledger=write_ledger,
                canonical_existing_count=len(canonical_existing or []),
                ledger_row_preview=ledger_preview,
            ),
            "notes": (
                f"runner aborted: abort_reason={abort_reason}. "
                f"invalid={len(invalid_claims)}, write 0."
            ),
        }

    if abort_reason == "no_evidence":
        # 비정상 (evidence 가 있었는데 runner 가 no_evidence 라고 하는 경우)
        # → skeleton 으로 처리 (raise 0).
        return {
            **base,
            "status": STATUS_SKELETON,
            "warning_code": "no_evidence_unexpected",
            "extraction": result,
            "llm_calls": llm_calls,
            "notes": "runner returned no_evidence unexpectedly.",
        }

    # Normal completion path — valid/invalid 분리됨
    valid_count = len(valid_claims)
    invalid_count = len(invalid_claims)

    # F-9 — period mismatch (plan 전에 detect)
    period_mismatch_ids = _period_mismatch_ids(valid_claims, period)

    # Build promotion plan (valid 가 비어도 호출 → 빈 plan, F-5 처리)
    try:
        plan = build_promotion_plan(
            valid_claims,
            rule=rule,
            force_ids=force_promote_ids,
            canonical_existing=canonical_existing,
            merge_policy=DEFAULT_MERGE_POLICY,
        )
    except Exception as exc:
        plan = None
        plan_error = f"plan_unavailable: {exc}"
    else:
        plan_error = None

    canonical_existing_count = int(
        (plan or {}).get("canonical_existing_count", len(canonical_existing or []))
    )

    # Status 결정 — 우선순위
    #   F-4 valid==0 (invalid 여부 무관)
    # > F-9 period_mismatch
    # > F-6 out_of_band
    # > F-10 merge_conflict_preview
    # > F-5 promotion_zero
    # > F-3 partial_extraction (invalid > 0)
    # > F-8 partial_extraction (actual_cost > cap)
    # > ok_plan_ready
    warnings = list(result.get("warnings") or [])
    status = STATUS_OK_PLAN_READY
    warning_code: str | None = None

    if valid_count == 0:
        status = STATUS_NO_VALID_CLAIMS
        warning_code = "no_claims_extracted"
    elif period_mismatch_ids:
        status = STATUS_PERIOD_MISMATCH
        warning_code = "period_inconsistent"
    elif plan and plan.get("out_of_band"):
        status = STATUS_PROMOTION_OUT_OF_BAND
        warning_code = "promotion_rate_violation"
    elif plan and (
        plan.get("skip_reasons", {}).get("duplicate_existing", 0) > 0
        or plan.get("skip_reasons", {}).get("supporting_diff_existing", 0) > 0
        or plan.get("skip_reasons", {}).get("merge_conflict", 0) > 0
    ):
        status = STATUS_MERGE_CONFLICT_PREVIEW
        warning_code = "merge_skip_existing"
    elif plan and plan.get("promoted_count", 0) == 0:
        status = STATUS_PROMOTION_ZERO
        warning_code = "no_promotion_passed"
    elif invalid_count > 0:
        status = STATUS_PARTIAL_EXTRACTION
        warning_code = "validator_partial"
    elif actual_cost > cost_cap_usd:
        # F-8 overlay (정상이지만 cost 초과)
        status = STATUS_PARTIAL_EXTRACTION
        warning_code = "cost_cap_exceeded_actual"

    if plan_error:
        warnings.append(plan_error)

    # Ledger row preview (Commit 3 — write 0)
    rule_breakdown = (plan or {}).get(
        "rule_breakdown", {"A": 0, "B": 0, "C": 0}
    )
    skip_reasons = (plan or {}).get("skip_reasons", {})
    promoted_count = int((plan or {}).get("promoted_count", 0) or 0)
    skipped_count = int((plan or {}).get("skipped_count", 0) or 0)
    promotion_rate = float((plan or {}).get("promotion_rate", 0.0) or 0.0)

    # C4 — write gate 평가 (G-11/G-12/G-13)
    write_allowed, write_block_reason = _evaluate_write_gate(
        status=status,
        plan=plan,
        invalid_count=invalid_count,
        actual_cost=actual_cost,
        cost_cap_usd=cost_cap_usd,
        write_canonical=write_canonical,
        write_wiki=write_wiki,
        write_ledger=write_ledger,
        allow_out_of_band=allow_out_of_band,
        target_suffix=target_suffix,
    )

    # out_of_band drift surface warning (C4 §6.2)
    if (
        status == STATUS_PROMOTION_OUT_OF_BAND
        and write_block_reason == "out_of_band_default_block"
    ):
        warnings.append(
            f"promotion_rate={promotion_rate:.1f}% is out-of-band relative to "
            f"R9-A.2 acceptance band [30.0, 70.0]; --allow-out-of-band 미지정 → "
            "canonical/wiki/ledger write 차단. R9-A.1 manual pilot rate=36.4% "
            "대비 drift 가능 — Rule B / prompt calibration 은 9.3b/Commit 5 트랙."
        )

    ledger_preview = build_ledger_row_preview(
        ts=ts,
        period=period,
        input_count=len(evidence_items),
        valid_claim_count=valid_count,
        invalid_claim_count=invalid_count,
        promoted_count=promoted_count,
        skipped_count=skipped_count,
        promotion_rate=promotion_rate,
        rule=rule,
        rule_breakdown=rule_breakdown,
        skip_reasons=skip_reasons,
        cost_usd=actual_cost,
        monthly_cost_usd_so_far=monthly_so_far,
        dry_run=(not write_allowed),
        write_canonical=write_canonical,
        write_wiki=write_wiki,
        write_ledger=write_ledger,
        status=status,
        abort_reason=None,
        warnings=warnings,
        out_of_band_override=bool(allow_out_of_band and plan and plan.get("out_of_band")),
        target_suffix=target_suffix,
        write_allowed=write_allowed,
        write_block_reason=write_block_reason,
        allow_out_of_band=allow_out_of_band,
        write_claims=bool(write_canonical and write_wiki and write_ledger),
        monthly_cost_before=monthly_so_far,
        monthly_cost_after_estimate=monthly_so_far + actual_cost,
        candidate_count=valid_count,
        canonical_existing_conflict_count=len((plan or {}).get("merge_conflicts", [])),
        # R9-A.22B — group monitoring traceability passthrough
        group_monitoring_summary_path=group_monitoring_summary_path,
        related_group_ids=related_group_ids,
        linked_wiki_claim_ids=linked_wiki_claim_ids,
        monitoring_mode=monitoring_mode,
        stable_candidate_counts=stable_candidate_counts,
    )

    would_save = _build_would_save(
        period=period,
        target_suffix=target_suffix,
        plan=plan,
        valid_count=valid_count,
        write_canonical=write_canonical,
        write_wiki=write_wiki,
        write_ledger=write_ledger,
        canonical_existing_count=canonical_existing_count,
        ledger_row_preview=ledger_preview,
    )

    # invalid raw dump path — C3-Q6 default B (explicit flag)
    if write_invalid_dump and dry_run_debug_path is not None and invalid_count > 0:
        would_save.append({
            "kind": "invalid_raw_dump",
            "path": str(dry_run_debug_path),
            "enabled_in_this_commit": False,
            "invalid_count": invalid_count,
        })

    # ── C4-γ — 실 write 분기 (G-1~G-13 통과 시) ──
    actually_saved: list[dict] = []
    writes = 0
    if write_allowed:
        try:
            from market_research.analyze.claim_store import (
                append_promotion_ledger,
                save_claims_canonical,
            )
            from market_research.wiki.claim_pages import promote_claims

            source = str(result.get("source") or "daily_update_r9a4")
            extractor_version = str(
                result.get("extractor_version") or "r9a.4-haiku")

            # 1) canonical store — target_suffix 필수 (G-13 통과 보장)
            canonical_path = save_claims_canonical(
                period=period,
                claims=valid_claims,
                source=source,
                extractor_version=extractor_version,
                promotion_result=plan,
                target_suffix=target_suffix,
            )
            actually_saved.append({
                "kind": "canonical_store",
                "path": str(canonical_path),
            })
            writes += 1

            # 2) wiki 08_Claims — promote_claims (idempotent + target_suffix
            #    분리, C4.1)
            wiki_result = promote_claims(
                valid_claims,
                rule=rule,
                force_ids=force_promote_ids,
                dry_run=False,
                target_suffix=target_suffix,
            )
            actually_saved.append({
                "kind": "wiki_08_claims",
                "promoted_count": wiki_result.get("promoted_count", 0),
                "skipped_count": wiki_result.get("skipped_count", 0),
                "target_suffix": target_suffix,
            })
            writes += int(wiki_result.get("promoted_count", 0) or 0)

            # 3) promotion ledger — 33필드 row append (target_suffix 분리, C4.1)
            append_promotion_ledger(ledger_preview, target_suffix=target_suffix)
            actually_saved.append({
                "kind": "promotion_ledger",
                "row_status": ledger_preview.get("status"),
            })
            writes += 1
        except Exception as exc:
            # Write 도중 실패 — graceful (D-6). write_allowed 는 True 였으나
            # 실 write 가 일부만 진행됐을 수 있음 → block_reason overlay.
            warnings.append(f"write_execution_error: {exc}")
            write_allowed = False
            write_block_reason = "write_execution_error"

    notes = (
        f"Step 2.7 enabled. runner 호출 {llm_calls}회. "
        f"status={status} warning_code={warning_code} "
        f"write_allowed={write_allowed} block={write_block_reason}. "
        f"valid={valid_count} invalid={invalid_count} "
        f"promoted={promoted_count} promotion_rate={promotion_rate:.1f}%. "
        f"cost=${actual_cost:.4f} monthly=${monthly_so_far:.4f}. "
        f"writes={writes}."
    )

    out = {
        **base,
        "status": status,
        "warning_code": warning_code,
        "llm_calls": llm_calls,
        "writes": writes,
        "extraction": result,
        "plan": plan,
        "ledger_row_preview": ledger_preview,
        "period_mismatch_ids": period_mismatch_ids,
        "would_save": would_save,
        "actually_saved": actually_saved,
        "notes": notes,
    }
    # base 의 monitoring 기본값을 실측값으로 덮어쓰기
    out["write_allowed"] = bool(write_allowed)
    out["write_block_reason"] = write_block_reason
    out["candidate_count"] = valid_count
    out["canonical_existing_conflict_count"] = len(
        (plan or {}).get("merge_conflicts", [])
    )
    return out
