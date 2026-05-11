# -*- coding: utf-8 -*-
"""R9-A.4 Commit 5 — Rule B calibration 회귀 (workorder "commit5_ruleb").

옵션 A'' 적용: chain≥3 + supporting_evidence_ids≥2.

본 모듈 검증 카테고리:
  A. drift fixture 재평가 — synthetic 18-claim (9.3b 분포 mimic) → rate 66.7%
  B. Rule B boundary — chain/sup_ev 4가지 경계
  C. Rule A/C 회귀 — 기존 동작 보존
  D. fail_reason breakdown — chain_too_short / insufficient_supporting_evidence
  E. 9.2 fixture passthrough (있을 때만) — 실 데이터 in-band 진입 확인
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_research.pipeline.claim_promotion_plan import build_promotion_plan
from market_research.wiki.claim_pages import (
    RULE_B_CHAIN_MIN,
    RULE_B_SUPPORTING_EV_MIN,
    _meets_rule_a,
    _meets_rule_b,
    _rule_b_diagnose,
)


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _claim(
    cid_suffix: str,
    *,
    chain_len: int = 3,
    sup_ev_count: int = 2,
    asset_count: int = 2,
    confidence: float = 0.9,
    salience: float = 0.9,
):
    """가변 chain/sup_ev/asset count claim 생성기 (다 사람 판독 가능)."""
    return {
        "schema_version": "1.0.0",
        "claim_id": f"claim:2026-04:{cid_suffix}",
        "period": "2026-04",
        "source_evidence_ids": [f"se_{cid_suffix}_{i}"
                                 for i in range(max(sup_ev_count, 1))],
        "claim_text": (
            f"Rule B calibration fixture {cid_suffix} — chain={chain_len} "
            f"sup={sup_ev_count} assets={asset_count}."
        ),
        "claim_type": "event_to_macro",
        "affected_assets": [
            {"asset_class": ac, "direction": "positive"}
            for ac in (
                ["국내주식", "해외주식", "국내채권",
                 "해외채권", "크레딧"][:asset_count]
            )
        ],
        "causal_chain": [
            {"source": f"s{i}", "target": f"t{i}", "relation": "raises"}
            for i in range(chain_len)
        ],
        "direction": "positive",
        "horizon": "short",
        "confidence": confidence,
        "salience": salience,
        "supporting_evidence_ids": [f"se_{cid_suffix}_{i}"
                                     for i in range(sup_ev_count)],
        "counter_evidence_ids": [],
        "linked_wiki_pages": [],
        "extractor_version": "r9a.4-haiku",
        "extraction_method": "llm",
        "warnings": [],
    }


# ──────────────────────────────────────────────────────────────────
# 임계 상수 회귀
# ──────────────────────────────────────────────────────────────────

def test_c5_thresholds_locked():
    """C5 calibration 상수 — 9.3b 분석 기반 결정값."""
    assert RULE_B_CHAIN_MIN == 3
    assert RULE_B_SUPPORTING_EV_MIN == 2


# ──────────────────────────────────────────────────────────────────
# B. Rule B boundary (4 cases per workorder)
# ──────────────────────────────────────────────────────────────────

def test_c5_B_chain2_sup2_rejected():
    """chain=2, sup=2 → chain_too_short 사유로 탈락."""
    c = _claim("b1c2s2", chain_len=2, sup_ev_count=2, asset_count=1)
    ok, reason = _rule_b_diagnose(c)
    assert ok is False
    assert reason == "chain_too_short"


def test_c5_B_chain3_sup1_rejected():
    """chain=3, sup=1 → insufficient_supporting_evidence."""
    c = _claim("b2c3s1", chain_len=3, sup_ev_count=1, asset_count=1)
    ok, reason = _rule_b_diagnose(c)
    assert ok is False
    assert reason == "insufficient_supporting_evidence"


def test_c5_B_chain3_sup2_pass():
    """chain=3, sup=2 → 통과 (calibrated 임계 정확히 만족)."""
    c = _claim("b3c3s2", chain_len=3, sup_ev_count=2, asset_count=1)
    ok, reason = _rule_b_diagnose(c)
    assert ok is True
    assert reason is None


def test_c5_B_chain4_sup2_pass():
    """chain=4, sup=2 → 통과 (임계 초과)."""
    c = _claim("b4c4s2", chain_len=4, sup_ev_count=2, asset_count=1)
    ok, reason = _rule_b_diagnose(c)
    assert ok is True
    assert reason is None


def test_c5_B_extreme_cases():
    """경계 외 추가 — chain=10/sup=0, chain=0/sup=5 등."""
    # chain 길어도 sup 부족 → 여전히 탈락
    c1 = _claim("bxc10s0", chain_len=10, sup_ev_count=0, asset_count=1)
    ok, reason = _rule_b_diagnose(c1)
    assert ok is False
    assert reason == "insufficient_supporting_evidence"

    # chain 부족하면 sup 많아도 탈락 (chain 먼저 검사)
    c2 = _claim("bxc1s5", chain_len=1, sup_ev_count=5, asset_count=1)
    ok, reason = _rule_b_diagnose(c2)
    assert ok is False
    assert reason == "chain_too_short"


# ──────────────────────────────────────────────────────────────────
# A. drift fixture 재평가 (synthetic 18-claim, 9.3b 분포 mimic)
# ──────────────────────────────────────────────────────────────────

def _drift_fixture_mimic_93b() -> list[dict]:
    """9.3b 18-claim 분포 모사:
      - 1 claim chain=2, sup=2 → chain_too_short (rejected)
      - 11 claim chain=3, sup=2 → pass
      - 5 claim chain=3, sup=1 → insufficient (rejected)
      - 1 claim chain=4, sup=2 → pass
    Expected: 12 promoted / 6 skipped / rate 66.67%
    """
    claims = []
    claims.append(_claim("d00", chain_len=2, sup_ev_count=2, asset_count=2))
    for i in range(11):
        claims.append(_claim(f"d{i+1:02d}p3s2", chain_len=3,
                              sup_ev_count=2, asset_count=2))
    for i in range(5):
        claims.append(_claim(f"d{i+12:02d}p3s1", chain_len=3,
                              sup_ev_count=1, asset_count=2))
    claims.append(_claim("d17p4s2", chain_len=4, sup_ev_count=2, asset_count=2))
    assert len(claims) == 18
    return claims


def test_c5_A_drift_mimic_in_band():
    """synthetic 18-claim → calibrated rate ~66.7%, in-band, out_of_band=False."""
    claims = _drift_fixture_mimic_93b()
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["input_count"] == 18
    assert plan["promoted_count"] == 12
    assert plan["skipped_count"] == 6
    assert plan["promotion_rate"] == 66.67
    assert plan["out_of_band"] is False
    # rule_breakdown: assets=2 (Rule A fail), so all promotions via Rule B
    assert plan["rule_breakdown"]["A"] == 0
    assert plan["rule_breakdown"]["B"] == 12
    assert plan["rule_breakdown"]["C"] == 0


def test_c5_A_drift_mimic_skip_reasons_breakdown():
    """drift fixture 의 skip_reasons 가 fail_reason 별 정확히 분기."""
    claims = _drift_fixture_mimic_93b()
    plan = build_promotion_plan(claims, rule="auto")
    sr = plan["skip_reasons"]
    assert sr["rule_a_b_unmet"] == 6
    assert sr["rule_b_chain_too_short"] == 1   # 1 chain=2 claim
    assert sr["rule_b_insufficient_supporting_evidence"] == 5  # 5 chain=3/sup=1


def test_c5_A_thresholds_echoed_in_plan():
    """plan dict 에 rule_b_thresholds 가 노출되어 monitoring 가능."""
    plan = build_promotion_plan(_drift_fixture_mimic_93b(), rule="auto")
    assert "rule_b_thresholds" in plan
    assert plan["rule_b_thresholds"]["chain_min"] == 3
    assert plan["rule_b_thresholds"]["supporting_ev_min"] == 2


# ──────────────────────────────────────────────────────────────────
# C. Rule A/C 회귀
# ──────────────────────────────────────────────────────────────────

def test_c5_C_rule_a_still_active_when_assets_3():
    """assets≥3, s/c≥0.7 시 Rule A 그대로 통과 (chain/sup 무관)."""
    c = _claim("ra1", chain_len=1, sup_ev_count=0, asset_count=3)
    assert _meets_rule_a(c) is True
    plan = build_promotion_plan([c], rule="auto")
    assert plan["promoted_count"] == 1
    assert plan["rule_breakdown"]["A"] == 1
    assert plan["rule_breakdown"]["B"] == 0


def test_c5_C_rule_a_fail_paths_unchanged():
    """Rule A 의 3 조건 (s>=0.7 / c>=0.7 / assets>=3) 각각 미달 시 Rule A 탈락."""
    # asset<3
    c1 = _claim("rai_a", asset_count=2, chain_len=1, sup_ev_count=0)
    assert _meets_rule_a(c1) is False
    # confidence<0.7
    c2 = _claim("rai_c", asset_count=3, confidence=0.5, chain_len=1,
                 sup_ev_count=0)
    assert _meets_rule_a(c2) is False
    # salience<0.7
    c3 = _claim("rai_s", asset_count=3, salience=0.5, chain_len=1,
                 sup_ev_count=0)
    assert _meets_rule_a(c3) is False


def test_c5_C_rule_c_force_ids_preserved():
    """force_ids → Rule C 그대로 (chain/sup 무관 강제 promote)."""
    c = _claim("rc1", chain_len=1, sup_ev_count=0, asset_count=1)
    plan = build_promotion_plan(
        [c], force_ids=["claim:2026-04:rc1"],
    )
    assert plan["promoted_count"] == 1
    assert plan["rule_breakdown"]["C"] == 1
    assert plan["rule_breakdown"]["A"] == 0
    assert plan["rule_breakdown"]["B"] == 0


# ──────────────────────────────────────────────────────────────────
# D. fail_reason breakdown — 자세한 케이스
# ──────────────────────────────────────────────────────────────────

def test_c5_D_breakdown_chain_only():
    """모두 chain=2 → 모두 chain_too_short."""
    claims = [
        _claim(f"d_chain_{i}", chain_len=2, sup_ev_count=3, asset_count=2)
        for i in range(5)
    ]
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["promoted_count"] == 0
    assert plan["skip_reasons"]["rule_b_chain_too_short"] == 5
    assert plan["skip_reasons"]["rule_b_insufficient_supporting_evidence"] == 0


def test_c5_D_breakdown_sup_ev_only():
    """모두 chain=4/sup=0 → 모두 insufficient_supporting_evidence."""
    claims = [
        _claim(f"d_sup_{i}", chain_len=4, sup_ev_count=0, asset_count=2)
        for i in range(5)
    ]
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["promoted_count"] == 0
    assert plan["skip_reasons"]["rule_b_insufficient_supporting_evidence"] == 5
    assert plan["skip_reasons"]["rule_b_chain_too_short"] == 0


def test_c5_D_mixed_fail_reasons():
    claims = [
        _claim("dm_a", chain_len=2, sup_ev_count=2, asset_count=2),  # chain
        _claim("dm_b", chain_len=3, sup_ev_count=1, asset_count=2),  # sup
        _claim("dm_c", chain_len=3, sup_ev_count=2, asset_count=2),  # pass
    ]
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["promoted_count"] == 1
    assert plan["skip_reasons"]["rule_b_chain_too_short"] == 1
    assert plan["skip_reasons"]["rule_b_insufficient_supporting_evidence"] == 1


# ──────────────────────────────────────────────────────────────────
# E. 실 Haiku fixture passthrough (optional, calibration 기준 검증)
#
# 중요 — Haiku 출력은 호출 간 wording variance 가 큼:
#   - 9.2 (5/8, $0.01384): chain={2:14, 3:4}, sup={1:6, 2:9, 3:2, 4:1}
#                          → new Rule B 적용 시 1/18 (5.6%, low out-of-band)
#   - 9.3b (5/11, $0.01655): chain={2:1, 3:16, 4:1}, sup={1:6, 2:4, 3:1, 4:5, 5:1, 6:1}
#                            → new Rule B 적용 시 12/18 (66.7%, in-band ✓)
#
# chain_analysis.md 의 calibration 기준은 9.3b. Commit 5 Rule B 임계도
# 9.3b 분포 기반 결정. 9.2 fixture 는 LLM variance 관찰용 보조 검증.
# ──────────────────────────────────────────────────────────────────

FIXTURE_92 = (Path(__file__).resolve().parents[2]
              / "debug/claims/r9a4_92_dryrun_result.json")
FIXTURE_93B = (Path(__file__).resolve().parents[2]
               / "debug/claims/r9a4_93b_haiku_result.json")


@pytest.mark.skipif(
    not FIXTURE_93B.exists(),
    reason=f"9.3b fixture not present: {FIXTURE_93B}",
)
def test_c5_E_93b_fixture_in_band():
    """9.3b 실 Haiku 결과 (calibration 기준) → rate 66.67%, in-band."""
    data = json.loads(FIXTURE_93B.read_text(encoding="utf-8"))
    # 9.3b 는 step_result envelope 안에 extraction 보관
    claims = data["step_result"]["extraction"]["claims"]
    assert len(claims) == 18
    plan = build_promotion_plan(claims, rule="auto")
    assert plan["input_count"] == 18
    assert plan["promoted_count"] == 12
    assert plan["promotion_rate"] == 66.67
    assert plan["out_of_band"] is False
    # Rule A 는 asset<3 이라 dead
    assert plan["rule_breakdown"]["A"] == 0
    assert plan["rule_breakdown"]["B"] == 12
    assert plan["rule_breakdown"]["C"] == 0
    # skip_reasons breakdown (9.3b 분포 기반):
    #   chain=2 1개 → chain_too_short
    #   chain=3 sup<2 5개 → insufficient_supporting_evidence
    #   (chain=4 1개는 sup>=2 면 통과, 분포 검증)
    sr = plan["skip_reasons"]
    assert sr["rule_a_b_unmet"] == 6
    assert sr["rule_b_chain_too_short"] == 1
    assert sr["rule_b_insufficient_supporting_evidence"] == 5


@pytest.mark.skipif(
    not FIXTURE_92.exists(),
    reason=f"9.2 fixture not present: {FIXTURE_92}",
)
def test_c5_E_92_fixture_variance():
    """9.2 fixture (calibration 기준 아님) — Haiku variance 관찰.

    9.2 는 chain 분포가 mostly=2 라 new Rule B 적용 시 rate=5.6% (low
    out-of-band). 본 테스트는 calibration 의 fragility 를 lock — 동일
    Haiku 라도 호출 시점별 분포 변동이 promotion rate 에 큰 영향.

    이는 Commit 5 가 단일 호출 분포 기반 임계 결정이므로 향후 (Commit 6+)
    더 강건한 calibration (예: scoring + multi-snapshot 평균) 필요성을
    시사. 본 commit 범위에서는 임계 결정값 보존만.
    """
    data = json.loads(FIXTURE_92.read_text(encoding="utf-8"))
    claims = data["extraction"]["claims"]
    assert len(claims) == 18
    plan = build_promotion_plan(claims, rule="auto")
    # 9.2 분포: chain={2:14, 3:4}, sup={1:6, 2:9, 3:2, 4:1}
    # chain≥3 (4건) ∩ sup≥2 (12건) ⇒ 1건
    assert plan["promoted_count"] == 1
    assert plan["promotion_rate"] == round(1 / 18 * 100, 2)
    # rate ≈ 5.56% < 30% → out_of_band (low side)
    assert plan["out_of_band"] is True
    sr = plan["skip_reasons"]
    # chain=2 14건 → chain_too_short
    assert sr["rule_b_chain_too_short"] == 14
    # chain=3 sup=1 3건 → insufficient (총 4건 중 sup>=2 1건 통과)
    assert sr["rule_b_insufficient_supporting_evidence"] == 3


# ──────────────────────────────────────────────────────────────────
# 보조 — _meets_rule_b 와 _rule_b_diagnose 일관성
# ──────────────────────────────────────────────────────────────────

def test_c5_diagnose_consistent_with_meets():
    for ch in range(0, 6):
        for sp in range(0, 4):
            c = _claim(f"con_{ch}_{sp}", chain_len=ch, sup_ev_count=sp,
                        asset_count=1)
            assert _meets_rule_b(c) == _rule_b_diagnose(c)[0], (
                f"chain={ch} sup={sp}: inconsistent"
            )
