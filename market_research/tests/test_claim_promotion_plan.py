# -*- coding: utf-8 -*-
"""R9-A.4 Commit 3 (C3-α) — promotion plan builder 회귀.

LLM 호출 0 / file write 0 / filesystem read 0 (canonical_existing inject).
"""
from __future__ import annotations

from market_research.pipeline.claim_promotion_plan import (
    DEFAULT_MERGE_POLICY,
    build_promotion_plan,
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
