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


def test_draft_label_crypto_park():
    from market_research.analyze.research_audit import _draft_label
    assert _draft_label("기타", ["크립토"], ["US"], set(), set()) == ("기타", "DROP_OR_PARK")
    assert _draft_label("해외주식", ["크립토"], ["US"], set(), set())[1] == "DROP_OR_PARK"


def test_draft_label_region_mismatch():
    from market_research.analyze.research_audit import _draft_label
    # 국내채권인데 KR 없음(US 매크로) → 해외채권 FIX_ASSET
    assert _draft_label("국내채권", ["금리_채권"], ["US"], set(), set()) == ("해외채권", "FIX_ASSET")
    # 해외주식인데 KR 단독 → 국내주식 FIX_ASSET
    assert _draft_label("해외주식", [], ["KR"], set(), set()) == ("국내주식", "FIX_ASSET")


def test_draft_label_low_conviction_dynamic():
    from market_research.analyze.research_audit import _draft_label
    # low_conv set 은 동적 주입 — 하드코딩 아님
    assert _draft_label("환율(FX)", [], ["US"], set(), {"환율(FX)"})[1] == "LOW_CONVICTION"
    # 같은 자산이라도 low_conv set 에 없으면 PASS (월별 strength 따라 가변)
    assert _draft_label("환율(FX)", [], ["US"], set(), set())[1] == "PASS"
    assert _draft_label("국내주식", ["테크_AI_반도체"], ["KR"], set(), set()) == ("국내주식", "PASS")


def test_draft_label_unsupported_fact():
    from market_research.analyze.research_audit import _draft_label
    assert _draft_label("국내주식", [], ["KR"], {"NEED_SOURCE_ATTACH"}, set())[1] == "UNSUPPORTED_FACT"


def test_stratified_sample_diversity():
    claims = ([{"claim_id": f"b{i}", "stance": "bullish", "horizon": "short"} for i in range(10)]
              + [{"claim_id": f"x{i}", "stance": "bearish", "horizon": "long"} for i in range(3)])
    s = stratified_sample(claims, 6)
    stances = {c["stance"] for c in s}
    assert "bearish" in stances   # 소수 cell 도 포함 (round-robin)
    assert len({c["claim_id"] for c in s}) == len(s)  # 중복 없음
