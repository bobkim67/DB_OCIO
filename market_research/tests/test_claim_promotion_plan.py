# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-α) — promotion plan builder 회귀.

LLM 호출 0 / file write 0 / filesystem read 0 (canonical_existing inject).
"""
from __future__ import annotations

from market_research.pipeline.claim_promotion_plan import (
    DEFAULT_MERGE_POLICY,
    EVIDENCE_OVERLAP_DEDUP_THRESHOLD,
    build_promotion_plan,
    detect_dedup_candidates,
    is_out_of_band,
)


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _make_claim(
    claim_id: str = "claim:2026-04:aaaaaaaaaa",
    period: str = "2026-04",
    salience: float = 0.9,
    confidence: float = 0.9,
    affected_assets=None,
    supporting_evidence_ids=None,
    causal_chain=None,
    claim_text: str = "유의미한 운용 영향이 있는 sample claim text.",
):
    if affected_assets is None:
        affected_assets = [
            {"asset_class": "국내주식", "direction": "positive"},
            {"asset_class": "해외주식", "direction": "positive"},
            {"asset_class": "국내채권", "direction": "negative"},
        ]
    if supporting_evidence_ids is None:
        supporting_evidence_ids = ["art1"]
    if causal_chain is None:
        causal_chain = [{"source": "x", "target": "y", "relation": "raises"}]
    return {
        "schema_version": "1.0.0",
        "claim_id": claim_id,
        "period": period,
        "source_evidence_ids": ["art1", "art2"],
        "claim_text": claim_text,
        "claim_type": "event_to_macro",
        "affected_assets": affected_assets,
        "causal_chain": causal_chain,
        "direction": "positive",
        "horizon": "short",
        "confidence": confidence,
        "salience": salience,
        "supporting_evidence_ids": supporting_evidence_ids,
        "counter_evidence_ids": [],
        "linked_wiki_pages": [],
        "extractor_version": "r9a.4-haiku",
        "extraction_method": "llm",
        "warnings": [],
    }


# ──────────────────────────────────────────────────────────────────
# Case 1 — A3 rule pass (mixed promote / skip)
# ──────────────────────────────────────────────────────────────────

def test_case1_rule_a3_pass_partial():
    # 3 promote-eligible (s/c≥0.7, assets≥3) + 2 fail (assets<3)
    claims = [
        _make_claim(claim_id=f"claim:2026-04:promo{i:06x}",
                    supporting_evidence_ids=[f"art{i}"]) for i in range(3)
    ] + [
        _make_claim(
            claim_id=f"claim:2026-04:fail{i:07x}",
            affected_assets=[{"asset_class": "국내주식",
                              "direction": "positive"}],
            causal_chain=[{"source": "a", "target": "b",
                            "relation": "raises"}],
            supporting_evidence_ids=[f"artf{i}"],
        )
        for i in range(2)
    ]
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["input_count"] == 5
    assert plan["promoted_count"] == 3
    assert plan["skipped_count"] == 2
    assert plan["promotion_rate"] == 60.0
    assert plan["rule_breakdown"]["A"] == 3
    assert plan["skip_reasons"]["rule_a_b_unmet"] == 2
    assert plan["out_of_band"] is False
    # 6 entries (canonical + wiki) per promote
    assert len(plan["would_write"]) == 6
    assert plan["merge_policy"] == DEFAULT_MERGE_POLICY


# ──────────────────────────────────────────────────────────────────
# Case 2 — out-of-band detection (promotion_rate > 70)
# ──────────────────────────────────────────────────────────────────

def test_case2_out_of_band_high():
    # 100% promotion — out_of_band=True (> 70).
    claims = [
        _make_claim(claim_id=f"claim:2026-04:oob{i:07x}",
                    supporting_evidence_ids=[f"art{i}"]) for i in range(8)
    ]
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["promoted_count"] == 8
    assert plan["promotion_rate"] == 100.0
    assert plan["out_of_band"] is True


def test_case2b_out_of_band_low():
    # 10% promotion — out_of_band=True (< 30).
    claims = [_make_claim(claim_id="claim:2026-04:keepoob01")] + [
        _make_claim(
            claim_id=f"claim:2026-04:skip{i:06x}",
            affected_assets=[{"asset_class": "국내주식",
                              "direction": "positive"}],
            causal_chain=[{"source": "a", "target": "b",
                            "relation": "raises"}],
            supporting_evidence_ids=[f"artf{i}"],
        )
        for i in range(9)
    ]
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["promoted_count"] == 1
    assert plan["promotion_rate"] == 10.0
    assert plan["out_of_band"] is True


# ──────────────────────────────────────────────────────────────────
# Case 3 — merge conflict: duplicate_existing (same supporting)
# ──────────────────────────────────────────────────────────────────

def test_case3_merge_conflict_duplicate():
    cid = "claim:2026-04:dupedupe01"
    incoming = _make_claim(claim_id=cid, supporting_evidence_ids=["art1"])
    existing = _make_claim(claim_id=cid, supporting_evidence_ids=["art1"])
    plan = build_promotion_plan([incoming], canonical_existing=[existing])
    assert plan["promoted_count"] == 0
    assert plan["skipped_count"] == 1
    assert plan["skip_reasons"]["duplicate_existing"] == 1
    assert plan["skip_reasons"]["supporting_diff_existing"] == 0
    assert len(plan["merge_conflicts"]) == 1
    assert plan["merge_conflicts"][0]["conflict_type"] == "duplicate_existing"
    assert plan["canonical_existing_count"] == 1


# ──────────────────────────────────────────────────────────────────
# Case 4 — merge conflict: supporting_evidence_ids 다름
# ──────────────────────────────────────────────────────────────────

def test_case4_merge_conflict_supporting_diff():
    cid = "claim:2026-04:diffdiff01"
    incoming = _make_claim(claim_id=cid,
                            supporting_evidence_ids=["art1", "art2"])
    existing = _make_claim(claim_id=cid,
                            supporting_evidence_ids=["art1"])
    plan = build_promotion_plan([incoming], canonical_existing=[existing])
    assert plan["promoted_count"] == 0
    assert plan["skip_reasons"]["supporting_diff_existing"] == 1
    assert plan["merge_conflicts"][0]["conflict_type"] == "supporting_diff_existing"


# ──────────────────────────────────────────────────────────────────
# Case 5 — Rule C (force_ids) 강제 promote
# ──────────────────────────────────────────────────────────────────

def test_case5_force_promote_rule_c():
    # rule_a/b 미달 — affected_assets=1, no causal chain
    bad = _make_claim(
        claim_id="claim:2026-04:forceonlyc",
        affected_assets=[{"asset_class": "국내주식",
                          "direction": "positive"}],
        causal_chain=[{"source": "a", "target": "b", "relation": "raises"}],
        supporting_evidence_ids=["art_force"],
    )
    plan = build_promotion_plan(
        [bad], force_ids=["claim:2026-04:forceonlyc"],
    )
    assert plan["promoted_count"] == 1
    assert plan["rule_breakdown"]["C"] == 1
    assert plan["rule_breakdown"]["A"] == 0
    assert plan["rule_breakdown"]["B"] == 0


# ──────────────────────────────────────────────────────────────────
# Auxiliary checks
# ──────────────────────────────────────────────────────────────────

def test_is_out_of_band_thresholds():
    assert is_out_of_band(29.9) is True
    assert is_out_of_band(30.0) is False
    assert is_out_of_band(70.0) is False
    assert is_out_of_band(70.1) is True


def test_empty_input_no_out_of_band():
    plan = build_promotion_plan([], rule="auto")
    assert plan["input_count"] == 0
    assert plan["promoted_count"] == 0
    assert plan["out_of_band"] is False


# ──────────────────────────────────────────────────────────────────
# R9-A.5.1 — evidence-overlap (Jaccard) dedup candidate diagnostic
# ──────────────────────────────────────────────────────────────────

def test_r9a51_threshold_constant_default():
    """Workorder — EVIDENCE_OVERLAP_DEDUP_THRESHOLD 상수가 0.50."""
    assert EVIDENCE_OVERLAP_DEDUP_THRESHOLD == 0.50


def test_r9a51_case_a_overlap_sufficient():
    """Case A — claim_1 {a,b,c} vs claim_2 {b,c,d}: jaccard 2/4=0.50 → 후보."""
    c1 = _make_claim(claim_id="claim:2026-04:caseaA00001",
                     supporting_evidence_ids=["a", "b", "c"])
    c2 = _make_claim(claim_id="claim:2026-04:caseaA00002",
                     supporting_evidence_ids=["b", "c", "d"])
    cands = detect_dedup_candidates([c1, c2])
    assert len(cands) == 1
    pair = cands[0]
    assert pair["claim_id_a"] == "claim:2026-04:caseaA00001"
    assert pair["claim_id_b"] == "claim:2026-04:caseaA00002"
    assert pair["jaccard"] == 0.5
    assert pair["shared_evidence_count"] == 2
    assert pair["union_evidence_count"] == 4
    assert pair["reason"] == "evidence_overlap"


def test_r9a51_case_b_overlap_zero():
    """Case B — disjoint evidence: jaccard=0 → 후보 0."""
    c1 = _make_claim(claim_id="claim:2026-04:casebB00001",
                     supporting_evidence_ids=["a", "b", "c"])
    c2 = _make_claim(claim_id="claim:2026-04:casebB00002",
                     supporting_evidence_ids=["d", "e", "f"])
    cands = detect_dedup_candidates([c1, c2])
    assert cands == []


def test_r9a51_case_c_empty_evidence():
    """Case C — 한쪽 evidence 비어있음: 에러 없이 skip."""
    c1 = _make_claim(claim_id="claim:2026-04:caseccC00001",
                     supporting_evidence_ids=[])
    c2 = _make_claim(claim_id="claim:2026-04:caseccC00002",
                     supporting_evidence_ids=["a", "b"])
    cands = detect_dedup_candidates([c1, c2])
    assert cands == []
    # 양쪽 모두 empty 도 안전.
    c3 = _make_claim(claim_id="claim:2026-04:caseccC00003",
                     supporting_evidence_ids=[])
    cands2 = detect_dedup_candidates([c1, c3])
    assert cands2 == []


def test_r9a51_case_d_self_excluded():
    """Case D — 자기 자신 비교 제외 (동일 claim_id 가 2회 입력된 edge case)."""
    c1 = _make_claim(claim_id="claim:2026-04:caseddD00001",
                     supporting_evidence_ids=["a", "b", "c"])
    # 동일 cid 가 입력 list 에 두 번 들어와도 self-pair 발생 X.
    cands = detect_dedup_candidates([c1, dict(c1)])
    assert cands == []


def test_r9a51_three_claim_pairs():
    """3 claim 모두 overlap ≥ threshold — pair 3 개 (n choose 2) 모두 surface."""
    c1 = _make_claim(claim_id="claim:2026-04:trio_A00001",
                     supporting_evidence_ids=["a", "b", "c"])
    c2 = _make_claim(claim_id="claim:2026-04:trio_B00002",
                     supporting_evidence_ids=["a", "b", "c"])
    c3 = _make_claim(claim_id="claim:2026-04:trio_C00003",
                     supporting_evidence_ids=["a", "b", "c"])
    cands = detect_dedup_candidates([c1, c2, c3])
    assert len(cands) == 3
    # 모두 jaccard=1.0
    assert all(p["jaccard"] == 1.0 for p in cands)
    # deterministic ordering — claim_id_a asc 후 claim_id_b asc
    keys = [(p["claim_id_a"], p["claim_id_b"]) for p in cands]
    assert keys == sorted(keys)


def test_r9a51_jaccard_below_threshold_skipped():
    """jaccard 0.25 (1/4) < 0.50 → 후보 0."""
    c1 = _make_claim(claim_id="claim:2026-04:lowlow00001",
                     supporting_evidence_ids=["a", "b", "c"])
    c2 = _make_claim(claim_id="claim:2026-04:lowlow00002",
                     supporting_evidence_ids=["c", "d", "e", "f"])
    cands = detect_dedup_candidates([c1, c2])
    # 공통={c}, 합={a,b,c,d,e,f}=6, jaccard=1/6≈0.167
    assert cands == []


def test_r9a51_promotion_invariant_unchanged():
    """workorder §4 — dedup 추가가 promotion metric 들을 바꾸지 않음.

    Case1 (test_case1_rule_a3_pass_partial) 와 동일 fixture 사용 — 그러나
    promote-eligible 3 개 claim 의 evidence set 을 의도적으로 overlap 되게 만든다.
    dedup_candidates 가 채워지면서도 promoted_count / rule_breakdown /
    out_of_band 는 동일 결과가 나와야 함.
    """
    # 3 promote (s/c≥0.7, assets≥3, evidence 의도적 overlap jaccard=0.5).
    # 각 claim: {ev_sh1, ev_sh2, ev_unique_i} — pair 별
    #   |∩|=2 (ev_sh1, ev_sh2), |∪|=4 → jaccard=0.5 (≥ threshold).
    # + 2 fail (assets<3, evidence disjoint — dedup 무관).
    claims = [
        _make_claim(
            claim_id=f"claim:2026-04:invpromo{i:03d}",
            supporting_evidence_ids=["ev_sh1", "ev_sh2", f"ev_unique_{i}"],
        )
        for i in range(3)
    ] + [
        _make_claim(
            claim_id=f"claim:2026-04:invfail{i:03d}_x",
            affected_assets=[
                {"asset_class": "국내주식", "direction": "positive"}
            ],
            causal_chain=[
                {"source": "a", "target": "b", "relation": "raises"}
            ],
            supporting_evidence_ids=[f"artf{i}"],
        )
        for i in range(2)
    ]
    plan = build_promotion_plan(claims, rule="auto")

    # promotion invariant — case1 와 동일 결과 (dedup 추가가 영향 0)
    assert plan["input_count"] == 5
    assert plan["promoted_count"] == 3
    assert plan["skipped_count"] == 2
    assert plan["promotion_rate"] == 60.0
    assert plan["rule_breakdown"]["A"] == 3
    assert plan["skip_reasons"]["rule_a_b_unmet"] == 2
    assert plan["out_of_band"] is False
    assert len(plan["would_write"]) == 6

    # dedup diagnostic — 3 promote claim 들이 ev_sh1/ev_sh2 공유 → C(3,2)=3 pair
    assert plan["dedup_threshold"] == 0.50
    assert isinstance(plan["dedup_candidates"], list)
    assert len(plan["dedup_candidates"]) == 3
    for p in plan["dedup_candidates"]:
        assert p["reason"] == "evidence_overlap"
        assert "invpromo" in p["claim_id_a"]
        assert "invpromo" in p["claim_id_b"]
        assert p["jaccard"] == 0.5
        assert p["shared_evidence_count"] == 2
        assert p["union_evidence_count"] == 4


def test_r9a51_plan_dict_key_present_on_empty():
    """plan dict schema 일관성 — input 0 일 때도 dedup_candidates 키 존재."""
    plan = build_promotion_plan([], rule="auto")
    assert "dedup_candidates" in plan
    assert plan["dedup_candidates"] == []
    assert plan["dedup_threshold"] == 0.50


def test_r9a51_plan_dict_key_present_on_unknown_rule():
    """unknown_rule error path 에도 dedup_candidates 키 존재."""
    c1 = _make_claim(claim_id="claim:2026-04:errkey00001",
                     supporting_evidence_ids=["a", "b", "c"])
    c2 = _make_claim(claim_id="claim:2026-04:errkey00002",
                     supporting_evidence_ids=["a", "b", "c"])
    plan = build_promotion_plan([c1, c2], rule="bogus_rule")
    assert "dedup_candidates" in plan
    # input list 기준 — error 이전에 계산되므로 둘은 surface 됨.
    assert len(plan["dedup_candidates"]) == 1
    assert plan["error"].startswith("unknown_rule:")
