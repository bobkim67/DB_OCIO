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
    RULE_B_CHAIN_MIN,
    RULE_B_SUPPORTING_EV_MIN,
    _evaluate_rules,
    _rule_b_diagnose,
)


# Commit 3 default merge policy (C3-Q5 default A — D-5 결정값 유지).
DEFAULT_MERGE_POLICY: str = "prefer_higher_confidence"

# R9-A.5.1 — evidence-overlap (Jaccard) 기반 dedup candidate 탐지 임계.
# read-only diagnostic (promotion 결과 불변). 임계 이상 pair 만 surface.
EVIDENCE_OVERLAP_DEDUP_THRESHOLD: float = 0.50


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


def _evidence_set(claim: dict) -> set[str]:
    """claim 의 supporting_evidence_ids 를 set 으로 정규화 (str cast + dedup)."""
    sup = claim.get("supporting_evidence_ids") or []
    if not isinstance(sup, list):
        return set()
    return {str(x) for x in sup if x}


def detect_dedup_candidates(
    claims: list[dict],
    *,
    threshold: float = EVIDENCE_OVERLAP_DEDUP_THRESHOLD,
) -> list[dict]:
    """R9-A.5.1 — evidence-overlap (Jaccard) 기반 dedup candidate 탐지.

    Read-only diagnostic — promotion 결과는 변경하지 않는다.

    각 claim 쌍에 대해 supporting_evidence_ids 의 Jaccard similarity 를 계산해
    `threshold` (default 0.50) 이상이면 후보로 surface 한다. Workorder R9-A.5.1
    Case A~D 명세:
        A. overlap 충분 → 후보 (jaccard ≥ threshold)
        B. overlap 0 (shared 없음) → skip (jaccard=0 < threshold)
        C. evidence 없음 (한쪽 또는 양쪽 empty) → skip (shared=0 또는 union=0)
        D. 자기 자신 비교 금지 → i<j + claim_id 동일 가드

    Output per candidate:
        {
          "claim_id_a": str,         # sorted (a < b lexicographically)
          "claim_id_b": str,
          "jaccard": float (0~1, round 4),
          "shared_evidence_count": int,
          "union_evidence_count": int,
          "reason": "evidence_overlap"
        }

    Order: jaccard desc → claim_id_a asc → claim_id_b asc (deterministic).
    """
    sets: list[tuple[str, set[str]]] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = c.get("claim_id")
        if not isinstance(cid, str) or not cid:
            continue
        sets.append((cid, _evidence_set(c)))

    candidates: list[dict] = []
    n = len(sets)
    for i in range(n):
        cid_a, ev_a = sets[i]
        for j in range(i + 1, n):
            cid_b, ev_b = sets[j]
            if cid_a == cid_b:
                # Case D — 자기 자신 비교 제외 (동일 claim_id 가 중복 입력된 경우).
                continue
            union = ev_a | ev_b
            if not union:
                # Case C — 양쪽 evidence 모두 비어있음.
                continue
            shared = ev_a & ev_b
            if not shared:
                # Case B — shared=0 → jaccard=0 < threshold.
                continue
            jac = len(shared) / len(union)
            if jac < threshold:
                continue
            a, b = sorted([cid_a, cid_b])
            candidates.append({
                "claim_id_a": a,
                "claim_id_b": b,
                "jaccard": round(jac, 4),
                "shared_evidence_count": len(shared),
                "union_evidence_count": len(union),
                "reason": "evidence_overlap",
            })
    candidates.sort(
        key=lambda d: (-d["jaccard"], d["claim_id_a"], d["claim_id_b"])
    )
    return candidates


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
        rule_b_thresholds  : {"chain_min", "supporting_ev_min"}
        dedup_candidates   : list[dict]   # R9-A.5.1 — evidence-overlap Jaccard
                                          # diagnostic (read-only)
        dedup_threshold    : float        # echo (default 0.50)
    """
    force_set = {x for x in (force_ids or ()) if isinstance(x, str)}
    existing_index = _index_canonical(canonical_existing)

    promoted_claim_ids: list[str] = []
    skipped_claim_ids: list[str] = []
    rule_breakdown = {"A": 0, "B": 0, "C": 0}
    skip_reasons = {
        "rule_a_b_unmet": 0,
        # R9-A.4 Commit 5 — Rule B fail breakdown (chain / supporting_evidence)
        "rule_b_chain_too_short": 0,
        "rule_b_insufficient_supporting_evidence": 0,
        "duplicate_existing": 0,
        "supporting_diff_existing": 0,
        "validation_failed": 0,
        "merge_conflict": 0,  # manual_pilot_existing 등 별 카테고리 누적
    }
    would_write: list[dict] = []
    merge_conflicts: list[dict] = []

    input_list = [c for c in (claims or []) if isinstance(c, dict)]

    # R9-A.5.1 — evidence-overlap dedup candidate (read-only diagnostic).
    # input_list 전체 (promote/skip 무관) 대상 — promotion 흐름 0 영향.
    dedup_candidates = detect_dedup_candidates(input_list)

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
                "rule_b_thresholds": {
                    "chain_min": RULE_B_CHAIN_MIN,
                    "supporting_ev_min": RULE_B_SUPPORTING_EV_MIN,
                },
                "dedup_candidates": dedup_candidates,
                "dedup_threshold": EVIDENCE_OVERLAP_DEDUP_THRESHOLD,
                "error": f"unknown_rule:{rule!r}",
            }
        if not ok:
            skipped_claim_ids.append(cid)
            skip_reasons["rule_a_b_unmet"] += 1
            # R9-A.4 Commit 5 — Rule B 실패 시 사유 breakdown.
            # Rule A 가 통과해도 rule="B" 선택자라면 B 가 결정자. 보수적으로
            # 항상 B 진단 추가 (counter 는 독립, rule_a_b_unmet 와 합 가능).
            _, b_reason = _rule_b_diagnose(claim)
            if b_reason == "chain_too_short":
                skip_reasons["rule_b_chain_too_short"] += 1
            elif b_reason == "insufficient_supporting_evidence":
                skip_reasons["rule_b_insufficient_supporting_evidence"] += 1
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
        # Commit 5 — calibration 임계 echo (debug / monitoring 용도)
        "rule_b_thresholds": {
            "chain_min": RULE_B_CHAIN_MIN,
            "supporting_ev_min": RULE_B_SUPPORTING_EV_MIN,
        },
        # R9-A.5.1 — evidence-overlap (Jaccard) dedup diagnostic.
        "dedup_candidates": dedup_candidates,
        "dedup_threshold": EVIDENCE_OVERLAP_DEDUP_THRESHOLD,
    }
