# -*- coding: utf-8 -*-
"""D4 research audit 단위 테스트. LLM 0."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.analyze.research_audit import (  # noqa: E402
    extract_hard_facts, _grounded, check_claim_grounding, stratified_sample,
)


def test_extract_hard_facts_kinds():
    f = extract_hard_facts("코스피 7,981 돌파, CPI 3.8%, 수출 149.8% 급증, 금리 50bp 인상")
    assert "7,981" in f
    assert "3.8%" in f
    assert "149.8%" in f or "149.8" in str(f)
    assert any("50" in x for x in f)


def test_extract_drops_strength_decimal():
    # 0~1 bare decimal(strength/confidence 메아리)은 fact 아님
    assert "0.626" not in extract_hard_facts("consensus strength 0.626 유지")


def test_grounded_comma_insensitive():
    assert _grounded("7,981", "코스피가 7981선을 돌파")     # 콤마 무시 매칭
    assert not _grounded("8,500", "코스피가 7981선을 돌파")  # 없는 값


def test_claim_grounding_flags_unsupported():
    claim = {"claim_text": "코스피 9,999 돌파", "supporting_evidence_ids": ["e1"]}
    g = check_claim_grounding(claim, {"e1": "코스피가 6900선 부근"})
    assert "9,999" in g["unsupported"]


def test_claim_grounding_supported():
    claim = {"claim_text": "CPI 3.8% 기록", "supporting_evidence_ids": ["e1"]}
    g = check_claim_grounding(claim, {"e1": "4월 CPI 전년비 3.8% 상승"})
    assert g["unsupported"] == []


def test_stratified_sample_diversity():
    claims = ([{"claim_id": f"b{i}", "stance": "bullish", "horizon": "short"} for i in range(10)]
              + [{"claim_id": f"x{i}", "stance": "bearish", "horizon": "long"} for i in range(3)])
    s = stratified_sample(claims, 6)
    stances = {c["stance"] for c in s}
    assert "bearish" in stances   # 소수 cell 도 포함 (round-robin)
    assert len({c["claim_id"] for c in s}) == len(s)  # 중복 없음
