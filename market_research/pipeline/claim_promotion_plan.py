# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-α) — promotion plan builder (LLM 0, write 0).

R9-A.2 promotion rule A3 를 재사용해 plan dict 만 생성한다. 실 wiki/
canonical/ledger write 는 일체 하지 않는다 (Commit 4 책임).

Commit 3 invariant:
  - file write 0
  - LLM 호출 0
  - filesystem read 0 (canonical_existing 은 호출 측 inject)
  - R9-A.2 rule 임계 변경 0 (D-4 promotion threshold A3 유지)
  - `ACCEPTANCE_BAND = (30.0, 70.0)` 재사용

본 plan dict 은 step_claim_extract 의 failure matrix 분기 + would_save
조립 + ledger row preview 의 source 가 된다. 어떤 분기에서도 raise 0
(graceful — daily_update D-6 정책).
"""
from __future__ import annotations

from typing import Any, Iterable

from market_research.analyze.claim_extractor import validate_claim
from market_research.wiki.claim_pages import (
    ACCEPTANCE_BAND,
    _evaluate_rules,
)


# Commit 3 default merge policy (C3-Q5 default A — D-5 결정값 유지).
DEFAULT_MERGE_POLICY: str = "prefer_higher_confidence"


def _hash10_of(claim_id: str | None) -> str:
    """`claim:{period}:{hash10}` → trailing hash10. 비정상 입력은 'unknown'."""
    if not isinstance(claim_id, str) or ":" not in claim_id:
        return "unknown"
    return claim_id.rsplit(":", 1)[-1]


def _wiki_page_filename(claim: dict) -> str:
    """`{period}_claim_{hash10}.md` (08_Claims/ 하위 file 명)."""
    period = claim.get("period") or "unknown"
    return f"{period}_claim_{_hash10_of(claim.get('claim_id'))}.md"


def _supporting_set(claim: dict) -> tuple[str, ...]:
    sup = claim.get("supporting_evidence_ids") or []
    if not isinstance(sup, list):
        return tuple()
    return tuple(sorted(str(x) for x in sup))


def _index_canonical(canonical_existing: list[dict] | None) -> dict[str, dict]:
    if not canonical_existing:
        return {}
    out: dict[str, dict] = {}
    for c in canonical_existing:
        if not isinstance(c, dict):
            continue
        cid = c.get("claim_id")
        if isinstance(cid, str) and cid:
            out[cid] = c
    return out


def _detect_merge_conflict(
    new_claim: dict,
    existing: dict | None,
) -> tuple[str | None, dict | None]:
    """Return (conflict_type, detail) — None if no conflict.

    conflict_type:
        - "duplicate_existing"        : same claim_id + same supporting set
        - "supporting_diff_existing"  : same claim_id + supporting differs
        - "manual_pilot_existing"     : same claim_id + existing.source ends
                                         with manual_pilot (별 카테고리, §7.4)
    """
    if existing is None:
        return None, None

    new_sup = _supporting_set(new_claim)
    ex_sup = _supporting_set(existing)

    # source 가 manual_pilot 계열이면 별 카테고리 (§7.4 명시 — 보존 정책)
    src = str(existing.get("source") or new_claim.get("source") or "")
    if "manual_pilot" in src:
        kind = "manual_pilot_existing"
    elif new_sup == ex_sup:
        kind = "duplicate_existing"
    else:
        kind = "supporting_diff_existing"

    detail = {
        "claim_id": new_claim.get("claim_id"),
        "conflict_type": kind,
        "existing_supporting_count": len(ex_sup),
        "new_supporting_count": len(new_sup),
    }
    return kind, detail


def is_out_of_band(promotion_rate: float) -> bool:
    lo, hi = ACCEPTANCE_BAND
    return (promotion_rate < lo) or (promotion_rate > hi)


def build_promotion_plan(
    claims: list[dict],
    *,
    rule: str = "auto",
    force_ids: Iterable[str] = (),
    canonical_existing: list[dict] | None = None,
    merge_policy: str = DEFAULT_MERGE_POLICY,
) -> dict[str, Any]:
    """R9-A.2 rule A3 재사용 + canonical_existing 비교 + plan dict.

    Parameters
    ----------
    claims : list[dict]
        Pre-validated claims (extractor runner 결과). 비-dict 항목은 skip.
    rule : "auto" | "A" | "B" | "both"
        promotion rule selector (default "auto"). R9-A.2 ACCEPTANCE_BAND 동일.
    force_ids : iterable of claim_id
        Rule C — 강제 promote.
    canonical_existing : optional list[dict]
        Already-saved claims for the period (보통 load_claims_canonical(period)
        ["claims"]). None 이면 신규 period 로 간주 → merge conflict 0.
    merge_policy : str
        Commit 3 default "prefer_higher_confidence" (C3-Q5). plan dict 의
        meta 로만 기록 — 실 merge 는 Commit 4.

    Returns
    -------
    plan dict — 키 구조:
        promoted_claim_ids : list[str]
        skipped_claim_ids  : list[str]
        promoted_count     : int
        skipped_count      : int
        input_count        : int
        promotion_rate     : float (0~100)
        rule               : str
        rule_breakdown     : {"A": int, "B": int, "C": int}
        skip_reasons       : {
            "rule_a_b_unmet": int,
            "duplicate_existing": int,
            "supporting_diff_existing": int,
            "validation_failed": int,
            "merge_conflict": int,
        }
        out_of_band        : bool
        would_write        : list[{"kind", "claim_id", "wiki_page"}]
        merge_conflicts    : list[dict]   # per-claim conflict detail
        merge_policy       : str          # echo, Commit 4 에서 실 사용
        canonical_existing_count : int    # input snapshot
    """
    force_set = {x for x in (force_ids or ()) if isinstance(x, str)}
    existing_index = _index_canonical(canonical_existing)

    promoted_claim_ids: list[str] = []
    skipped_claim_ids: list[str] = []
    rule_breakdown = {"A": 0, "B": 0, "C": 0}
    skip_reasons = {
        "rule_a_b_unmet": 0,
        "duplicate_existing": 0,
        "supporting_diff_existing": 0,
        "validation_failed": 0,
        "merge_conflict": 0,  # manual_pilot_existing 등 별 카테고리 누적
    }
    would_write: list[dict] = []
    merge_conflicts: list[dict] = []

    input_list = [c for c in (claims or []) if isinstance(c, dict)]

    for claim in input_list:
        cid = claim.get("claim_id") or "(no id)"

        # 1) Defensive validate — runner 통과품인데 한 번 더 (claim_id 결손 case
        #    예외 대비).
        v = validate_claim(claim)
        if not v["valid"]:
            skipped_claim_ids.append(cid)
            skip_reasons["validation_failed"] += 1
            continue

        # 2) Rule A/B/C evaluation
        try:
            ok, applied = _evaluate_rules(claim, rule, force_set)
        except ValueError:
            # unknown rule → entire plan unusable, but graceful (D-6).
            return {
                "promoted_claim_ids": [],
                "skipped_claim_ids": [c.get("claim_id") for c in input_list],
                "promoted_count": 0,
                "skipped_count": len(input_list),
                "input_count": len(input_list),
                "promotion_rate": 0.0,
                "rule": rule,
                "rule_breakdown": rule_breakdown,
                "skip_reasons": skip_reasons,
                "out_of_band": False,
                "would_write": [],
                "merge_conflicts": [],
                "merge_policy": merge_policy,
                "canonical_existing_count": len(existing_index),
                "error": f"unknown_rule:{rule!r}",
            }
        if not ok:
            skipped_claim_ids.append(cid)
            skip_reasons["rule_a_b_unmet"] += 1
            continue

        # 3) Merge conflict (vs canonical_existing)
        existing = existing_index.get(cid)
        conflict_kind, conflict_detail = _detect_merge_conflict(claim, existing)
        if conflict_kind is not None:
            merge_conflicts.append(conflict_detail or {"claim_id": cid})
            skipped_claim_ids.append(cid)
            if conflict_kind in skip_reasons:
                skip_reasons[conflict_kind] += 1
            else:
                # manual_pilot_existing 등 → merge_conflict 누적
                skip_reasons["merge_conflict"] += 1
            continue

        # 4) Promote — plan only (write 0)
        promoted_claim_ids.append(cid)
        if applied in rule_breakdown:
            rule_breakdown[applied] += 1
        wiki_page = _wiki_page_filename(claim)
        would_write.append({
            "kind": "canonical_claim",
            "claim_id": cid,
            "wiki_page": wiki_page,
        })
        would_write.append({
            "kind": "wiki_08_claims",
            "claim_id": cid,
            "wiki_page": wiki_page,
        })

    n = len(input_list)
    promoted_count = len(promoted_claim_ids)
    skipped_count = len(skipped_claim_ids)
    promotion_rate = (promoted_count / n * 100.0) if n else 0.0

    return {
        "promoted_claim_ids": promoted_claim_ids,
        "skipped_claim_ids": skipped_claim_ids,
        "promoted_count": promoted_count,
        "skipped_count": skipped_count,
        "input_count": n,
        "promotion_rate": round(promotion_rate, 2),
        "rule": rule,
        "rule_breakdown": rule_breakdown,
        "skip_reasons": skip_reasons,
        "out_of_band": is_out_of_band(promotion_rate) if n else False,
        "would_write": would_write,
        "merge_conflicts": merge_conflicts,
        "merge_policy": merge_policy,
        "canonical_existing_count": len(existing_index),
    }
