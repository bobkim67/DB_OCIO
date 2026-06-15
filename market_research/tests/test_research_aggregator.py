# -*- coding: utf-8 -*-
"""Research aggregator + consensus page 단위 테스트 (P3/P4). LLM 0(deterministic)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.analyze.research_aggregator import (  # noqa: E402
    aggregate_by_asset, distribution_report,
)
from market_research.analyze.research_consensus import (  # noqa: E402
    build_research_synthesis_page, synthesize_asset_narrative,
)


def _claim(asset, stance, src="naver_research", horizon="medium",
           cid="abcd1234ef", risk="", view="v", sectors=None):
    return {
        "claim_id": f"claim:2026-05:{cid}", "primary_asset": asset, "stance": stance,
        "source_type": src, "horizon": horizon, "risk_factor": risk, "view": view,
        "broker_author": "키움증권" if src != "monygeek" else "monygeek",
        "claim_text": f"{asset} {stance}", "sectors": sectors or ["테크_AI_반도체"],
        "affected_assets": [{"asset_class": asset, "role": "primary"}],
    }


def _claims():
    return [
        _claim("국내주식", "bullish", cid="a1"),
        _claim("국내주식", "bullish", cid="a2"),
        _claim("국내주식", "bearish", cid="a3", risk="실적 둔화"),
        _claim("국내주식", "neutral", src="monygeek", cid="a4"),  # vote 제외
        _claim("해외채권", "bearish", cid="b1"),
    ]


def test_vote_excludes_monygeek():
    agg = aggregate_by_asset(_claims())
    ks = agg["국내주식"]
    # broker 3건만 vote (monygeek 1건 제외)
    assert sum(ks["vote_distribution"].values()) == 3
    assert ks["n_monygeek"] == 1
    assert ks["consensus_stance"] == "bullish"   # broker 2 bullish vs 1 bearish
    assert ks["n_broker"] == 3


def test_dissent_includes_monygeek_and_minority():
    agg = aggregate_by_asset(_claims())
    ks = agg["국내주식"]
    stances = [c.get("stance") for c in ks["dissent"]]
    assert "neutral" in stances   # monygeek
    assert "bearish" in stances   # broker 소수 stance
    assert "bullish" not in stances  # consensus 는 dissent 아님


def test_risk_factors_collected():
    agg = aggregate_by_asset(_claims())
    assert any("실적 둔화" in r for r in agg["국내주식"]["risk_factors"])


def test_distribution_report_warnings():
    agg = aggregate_by_asset(_claims())
    rep = distribution_report(agg, min_claims=3)
    # 해외채권 1건 → 부족 경고
    assert any("해외채권" in w and "부족" in w for w in rep["warnings"])
    assert rep["n_assets"] == 2


def test_page_build_deterministic_structure():
    agg = aggregate_by_asset(_claims())
    page = build_research_synthesis_page(
        "2026-05", "국내주식", agg["국내주식"],
        {"consensus_narrative": "", "dissent_narrative": ""})
    assert "asset_class: 국내주식" in page
    assert "consensus_stance: bullish" in page
    assert "## 1. 컨센서스" in page
    assert "## 2. 이견" in page
    assert "## 5. monygeek 관점" in page
    assert "[claim:a1]" in page   # claim trace ref


# ── region-aware rerouting (FIX_ASSET 6건 regression, 2026-06-15) ──

def _rc(asset, regions, text, sectors=None):
    return {"affected_assets": [{"asset_class": asset, "role": "primary"}],
            "primary_asset": asset, "regions": regions, "claim_text": text,
            "sectors": sectors or ["금리_채권"]}


def test_reroute_us_macro_to_overseas():
    # 실제 FIX_ASSET 6건 패턴 — 국내자산 + 비-KR region + KR 직접영향 無 → 해외
    from market_research.analyze.research_aggregator import _primary
    cases = [
        _rc("국내채권", ["US", "GLOBAL"], "미국 인플레이션 재상승 우려"),
        _rc("국내채권", ["US"], "수입물가 급등에 따른 인플레이션 경계감 심화"),
        _rc("국내채권", ["US", "GLOBAL"], "미국 스태그플레이션 리스크"),
        _rc("국내채권", ["US"], "인플레이션 압력 재격화"),
        _rc("국내주식", ["US", "GLOBAL"], "미국 고용 질적 악화 신호", ["경기_소비"]),
        _rc("국내주식", ["US", "GLOBAL"], "정책 변동성 상승", ["관세_무역"]),
    ]
    for c in cases:
        out = _primary(c)
        assert out.startswith("해외"), f"{c['claim_text']} → {out}"


def test_reroute_keeps_kr_when_kr_impact_explicit():
    # 미국 변수지만 한국 자산 직접 영향 명시 → 국내 유지 + driver_region=US
    from market_research.analyze.research_aggregator import _primary, claim_driver_region
    c = _rc("국내주식", ["US"], "미국 금리 상승이 코스피 외국인 수급에 직접 타격")
    assert _primary(c) == "국내주식"
    assert claim_driver_region(c) == "US"


def test_reroute_kr_region_unaffected():
    # regions 에 KR 있으면 reroute 안 함
    from market_research.analyze.research_aggregator import _primary
    assert _primary(_rc("국내채권", ["KR"], "한국 금리 동결")) == "국내채권"
    assert _primary(_rc("국내채권", ["KR", "US"], "한미 금리차")) == "국내채권"


def test_driver_region_classification():
    from market_research.analyze.research_aggregator import claim_driver_region
    assert claim_driver_region({"regions": ["KR"]}) == "KR"
    assert claim_driver_region({"regions": ["KR", "US"]}) == "mixed"
    assert claim_driver_region({"regions": ["US"]}) == "US"
    assert claim_driver_region({"regions": ["NON_US_OVERSEAS"]}) == "overseas"
    assert claim_driver_region({"regions": []}) is None


def test_synthesize_narrative_no_llm_returns_empty():
    agg = aggregate_by_asset(_claims())
    n = synthesize_asset_narrative("국내주식", agg["국내주식"], llm_call=None)
    assert n == {"consensus_narrative": "", "dissent_narrative": ""}
