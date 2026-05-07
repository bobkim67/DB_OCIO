"""R8-B-2 회귀: agent prompt 강화 + amc validation/fallback.

LLM 호출 0. 순수 단위 테스트.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_prompt_for(agent: str = "bull") -> str:
    """_build_agent_prompt 를 minimal context 로 호출하여 prompt 반환."""
    from market_research.report.debate_engine import _build_agent_prompt
    ctx = {
        "year": 2026, "month": 4, "fund_code": None,
        "news_summary_text": "(none)", "indicators_text": "(none)",
        "timeseries_narrative_text": "", "graph_paths_text": "",
        "wiki_context_text": "", "asset_coverage_text": "",
        "asset_movement_anchors_text": (
            "## Asset Movement Anchors (R8-B)\n"
            "[해외주식] rank=1 ...\n[국내채권] rank=2 ...\n[환율(FX)] rank=3 ...\n"
        ),
    }
    return _build_agent_prompt(agent, ctx)


# ──────────────────────────────────────────────────────────────────
# 1. prompt 에 amc 필수 instruction 포함
# ──────────────────────────────────────────────────────────────────

def test_prompt_contains_amc_required_instruction():
    p = _build_prompt_for()
    assert "## asset_movement_commentary (필수, R8-B-2 강화)" in p
    # 빈 배열 금지 / 최소 3개 명시
    assert "빈 배열 금지" in p
    assert "3개 이상" in p


def test_prompt_lists_priority_assets():
    p = _build_prompt_for()
    # 우선순위 자산군 5개 모두 prompt 에 명시
    for ac in ["해외주식", "국내채권", "환율(FX)", "원자재금", "국내주식"]:
        assert ac in p


def test_prompt_six_required_fields():
    p = _build_prompt_for()
    # 6개 필드 모두 명시
    for f in ["asset_class", "past_movement", "drivers",
              "causal_paths", "outlook", "portfolio_implication"]:
        assert f in p


def test_prompt_bm_missing_handling():
    p = _build_prompt_for()
    # BM 값 없을 때 임의 수치 생성 금지 + 정성 표현
    assert "수치 임의 생성 금지" in p
    assert "수익률 미확인 — 정성 평가" in p
    # fund BM 없는 경우 alpha/초과수익률 언급 금지
    assert "alpha" in p or "초과수익률 언급 금지" in p


def test_prompt_inline_json_example_has_three_assets():
    """inline JSON 예시에 최소 3개 자산군 (해외주식/국내채권/환율(FX)) 등장."""
    p = _build_prompt_for()
    # 예시 안에 자산군 3개 등장 (각각 별도 dict)
    n_examples = (
        p.count('"asset_class":"해외주식"')
        + p.count('"asset_class":"국내채권"')
        + p.count('"asset_class":"환율(FX)"')
    )
    assert n_examples >= 3, (
        f"expected >=3 example asset_class entries, got {n_examples}"
    )


# ──────────────────────────────────────────────────────────────────
# 2. validate_amc_response — empty / partial / valid
# ──────────────────────────────────────────────────────────────────

def test_validate_amc_empty_warning():
    from market_research.report.asset_movement_anchor import validate_amc_response
    # None
    ws = validate_amc_response(None)
    assert ws and any("missing" in w for w in ws)
    # empty list
    ws = validate_amc_response([])
    assert ws and any("empty" in w for w in ws)
    # < 3
    ws = validate_amc_response([{"asset_class": "해외주식",
                                  "past_movement": "x", "drivers": ["a"],
                                  "causal_paths": ["p"], "outlook": "o",
                                  "portfolio_implication": "pi"}])
    assert ws and any("≥3" in w or "only 1" in w for w in ws)


def test_validate_amc_partial_field_missing():
    from market_research.report.asset_movement_anchor import validate_amc_response
    bad = [
        {"asset_class": "해외주식", "past_movement": "-3%",
         # drivers 누락
         "causal_paths": ["p"], "outlook": "o", "portfolio_implication": "pi"},
        {"asset_class": "국내채권"},  # 거의 전부 누락
        {"asset_class": "환율(FX)", "past_movement": "x", "drivers": ["a"],
         "causal_paths": ["p"], "outlook": "o", "portfolio_implication": "pi"},
    ]
    ws = validate_amc_response(bad)
    # amc[0].drivers missing
    assert any("amc[0].drivers" in w for w in ws)
    # amc[1] 다수 missing
    assert any("amc[1].past_movement" in w for w in ws)


def test_validate_amc_valid_no_warning():
    from market_research.report.asset_movement_anchor import validate_amc_response
    good = [
        {"asset_class": "해외주식", "past_movement": "-3%",
         "drivers": ["성장주"], "causal_paths": ["geopolitical"],
         "outlook": "회복", "portfolio_implication": "OW 유지"},
        {"asset_class": "국내채권", "past_movement": "수익률 미확인",
         "drivers": ["통화정책"], "causal_paths": ["rates_domestic_bond"],
         "outlook": "상단 인식", "portfolio_implication": "듀레이션 확대"},
        {"asset_class": "환율(FX)", "past_movement": "+1.7%",
         "drivers": ["달러강세"], "causal_paths": ["fx_translation"],
         "outlook": "변동성", "portfolio_implication": "헤지 점검"},
    ]
    ws = validate_amc_response(good)
    assert ws == [], f"expected 0 warning, got: {ws}"


# ──────────────────────────────────────────────────────────────────
# 3. build_amc_fallback — anchors 기반 deterministic stub
# ──────────────────────────────────────────────────────────────────

def test_fallback_top3_from_anchors():
    from market_research.report.asset_movement_anchor import build_amc_fallback
    anchors = {
        "asset_movements": [
            {"asset_class": "원자재금", "movement_rank": 1,
             "bm": {"name": "Gold", "return_pct": 5.5},
             "topic_tags": ["귀금속_금"], "causal_paths": [
                 {"path_id": "gold_hedge_volatility"}]},
            {"asset_class": "환율(FX)", "movement_rank": 2,
             "bm": {"name": "USDKRW", "return_pct": 6.3},
             "topic_tags": ["환율_FX"], "causal_paths": []},
            {"asset_class": "해외주식", "movement_rank": 3,
             "bm": {"name": "S&P 500", "return_pct": -4.4},
             "topic_tags": ["테크_AI_반도체"], "causal_paths": [
                 {"path_id": "geopolitical_oil_inflation_rates_growth"}]},
            {"asset_class": "국내주식", "movement_rank": 4,
             "bm": {"name": "MSCI Korea", "return_pct": 26.5},
             "topic_tags": [], "causal_paths": []},
        ]
    }
    fb = build_amc_fallback(anchors, top_n=3)
    assert len(fb) == 3
    # rank 1, 2, 3 만 포함, rank 4 (국내주식) 제외
    assert [it["asset_class"] for it in fb] == ["원자재금", "환율(FX)", "해외주식"]
    # 각 항목 필수 6필드 + _source=fallback
    for it in fb:
        for f in ("asset_class", "past_movement", "drivers", "causal_paths",
                  "outlook", "portfolio_implication"):
            assert f in it
        assert it["_source"] == "fallback"
        assert "(deterministic fallback" in it["outlook"]


def test_fallback_bm_missing_uses_qualitative_string():
    from market_research.report.asset_movement_anchor import build_amc_fallback
    anchors = {
        "asset_movements": [
            {"asset_class": "국내채권", "movement_rank": 1,
             "bm": {"name": "BOK_RATE"},  # return_pct 없음
             "topic_tags": ["금리_채권"], "causal_paths": []},
        ]
    }
    fb = build_amc_fallback(anchors, top_n=3)
    assert fb
    assert "수익률 미확인" in fb[0]["past_movement"]


def test_fallback_empty_anchors_safe():
    from market_research.report.asset_movement_anchor import build_amc_fallback
    assert build_amc_fallback(None) == []
    assert build_amc_fallback({}) == []
    assert build_amc_fallback({"asset_movements": []}) == []


# ──────────────────────────────────────────────────────────────────
# 4. _run_agent guard 통합 — agent 가 amc empty 시 warning + fallback surface
# ──────────────────────────────────────────────────────────────────

def test_run_agent_emits_warning_and_fallback(monkeypatch):
    """LLM 호출 mock 으로 빈 amc 응답 → result 에 warnings + fallback."""
    import market_research.report.debate_engine as de

    def fake_call_llm(model, system, prompt, max_tokens=1500, log_label=''):
        # asset_movement_commentary 누락한 응답
        return ('{"stance":"neutral","key_points":["short"],'
                '"risk_assessment":"none","asset_allocation_view":{},'
                '"asset_movement_commentary":[],'
                '"tail_risks":[],"reasoning":"x"}')

    monkeypatch.setattr(de, "_call_llm", fake_call_llm)

    ctx = {
        "year": 2026, "month": 4, "fund_code": None,
        "news_summary_text": "(none)", "indicators_text": "(none)",
        "timeseries_narrative_text": "", "graph_paths_text": "",
        "wiki_context_text": "", "asset_coverage_text": "",
        "asset_movement_anchors_text": "## Asset Movement Anchors (R8-B)\n",
        "_asset_movement_anchors": {
            "asset_movements": [
                {"asset_class": "해외주식", "movement_rank": 1,
                 "bm": {"name": "S&P 500", "return_pct": -4.0},
                 "topic_tags": [], "causal_paths": []},
                {"asset_class": "국내채권", "movement_rank": 2,
                 "bm": {"name": "BOK"},
                 "topic_tags": [], "causal_paths": []},
                {"asset_class": "환율(FX)", "movement_rank": 3,
                 "bm": {"name": "USDKRW", "return_pct": 1.7},
                 "topic_tags": [], "causal_paths": []},
            ]
        },
    }
    result = de._run_agent("bull", ctx)
    assert isinstance(result, dict)
    assert result["asset_movement_commentary"] == []
    # warnings 별도 field
    ws = result.get("asset_movement_commentary_warnings") or []
    assert ws and any("empty" in w for w in ws)
    # fallback 별도 field, top3 자산군
    fb = result.get("asset_movement_commentary_fallback") or []
    assert len(fb) == 3
    assert [it["asset_class"] for it in fb] == ["해외주식", "국내채권", "환율(FX)"]
    # agent output 자체는 무수정 (amc 그대로 빈 list)
    assert result["asset_movement_commentary"] == []


# ──────────────────────────────────────────────────────────────────
# 5. parser 가 amc 필드를 보존 (회귀)
# ──────────────────────────────────────────────────────────────────

def test_parser_preserves_amc_field():
    """LLM 이 amc 를 채워 응답하면 parser 가 그대로 보존."""
    from market_research.report.debate_engine import _parse_json_response
    text = (
        '{"stance":"bullish","key_points":["a"],"risk_assessment":"r",'
        '"asset_allocation_view":{},'
        '"asset_movement_commentary":['
        '{"asset_class":"해외주식","past_movement":"-3%","drivers":["d1"],'
        '"causal_paths":["p1"],"outlook":"o","portfolio_implication":"pi"}'
        '],"tail_risks":[],"reasoning":"x"}'
    )
    res = _parse_json_response(text)
    assert isinstance(res, dict)
    amc = res.get("asset_movement_commentary")
    assert isinstance(amc, list) and len(amc) == 1
    assert amc[0]["asset_class"] == "해외주식"
    assert amc[0]["past_movement"] == "-3%"
