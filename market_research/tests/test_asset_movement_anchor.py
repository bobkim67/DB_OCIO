"""R8-B-impl 회귀: asset_movement_anchor + debate_engine + fund_comment / comment_trace 통합.

LLM 호출 0. tmp_path / mock 만 사용 — 운영 데이터 무접근.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _make_indicators_csv(tmp_path: Path) -> Path:
    """min indicators.csv — 한 달치 (4월) 시계열 2개 행."""
    csv_text = (
        "date,DXY,USDKRW,SP500_TR,MSCI_KOREA,GOLD,US_HY_OAS,FED_UPPER,UST_7_10Y_TR\n"
        "2026-04-01,103.0,1450.0,5500.0,90.0,2300.0,320.0,5.50,180.0\n"
        "2026-04-30,104.5,1500.0,5400.0,87.0,2400.0,340.0,5.50,178.5\n"
    )
    fp = tmp_path / "indicators.csv"
    fp.write_text(csv_text, encoding="utf-8")
    return fp


def _mock_evidence() -> list[dict]:
    """evidence_annotations mock — R8-A resolver 결과 schema."""
    return [
        {"ref": 1, "article_id": "ev1", "title": "이란 분쟁 격화 유가 100달러 돌파",
         "source": "Reuters", "date": "2026-04-15",
         "topic": "지정학", "all_topics": ["지정학"], "_resolved": True},
        {"ref": 2, "article_id": "ev2", "title": "FOMC 금리 동결, 성장주 반등",
         "source": "WSJ", "date": "2026-04-22",
         "topic": "금리_채권", "all_topics": ["금리_채권"], "_resolved": True},
        {"ref": 3, "article_id": "ev3", "title": "AI 빅테크 실적 호조 나스닥",
         "source": "FT", "date": "2026-04-25",
         "topic": "테크_AI_반도체", "all_topics": [], "_resolved": True},
        {"ref": 4, "article_id": "ev4", "title": "원달러 환율 1500원 돌파",
         "source": "한경", "date": "2026-04-28",
         "topic": "환율_FX", "_resolved": True},
        {"ref": 5, "article_id": "ev5", "title": "금 가격 안전자산 신고가",
         "source": "연합뉴스", "date": "2026-04-30",
         "topic": "귀금속_금", "_resolved": True},
        # 매칭 실패 (cross-asset event_geopolitical 단독)
        {"ref": 6, "article_id": "ev6", "title": "관세 위법 판결",
         "source": "WSJ", "date": "2026-04-20",
         "topic": "관세_무역", "_resolved": True},
        # unresolved → 자동 skip
        {"ref": 7, "article_id": "ev7", "title": "(매핑 실패)",
         "_resolved": False},
    ]


def _mock_paths() -> list[dict]:
    return [
        {"path_id": "geopolitical_oil_inflation_rates_growth",
         "label": "지정학 → 유가 → 인플레이션 → 금리 → 성장주",
         "confidence": 1.0,
         "covered_chain_nodes": ["event:geopolitical", "macro:oil_price",
                                  "macro:inflation", "macro:interest_rate",
                                  "asset:us_growth_stock"],
         "supporting_evidence_ids": ["ev1", "ev2", "ev3"]},
        {"path_id": "rates_domestic_bond",
         "label": "금리 → 국내채권",
         "confidence": 0.5,
         "covered_chain_nodes": ["macro:interest_rate"],
         "supporting_evidence_ids": ["ev2"]},
        {"path_id": "fx_translation_overseas_assets",
         "label": "환율 → 해외자산 환산",
         "confidence": 0.5,
         "covered_chain_nodes": ["macro:fx_usdkrw"],
         "supporting_evidence_ids": ["ev4"]},
        {"path_id": "gold_hedge_volatility",
         "label": "금 → 안전자산 헤지",
         "confidence": 1.0,
         "covered_chain_nodes": ["asset:gold"],
         "supporting_evidence_ids": ["ev5"]},
    ]


def _mock_pa_dataframe():
    """compute_single_port_pa 결과 mock — 8N81 시나리오."""
    import pandas as pd
    return pd.DataFrame([
        {"자산군": "포트폴리오", "개별수익률": 0.012, "기여수익률": 0.012, "순자산비중": 1.0, "순비중변화": 0},
        {"자산군": "국내주식", "개별수익률": -0.025, "기여수익률": -0.005, "순자산비중": 0.20, "순비중변화": 0.01},
        {"자산군": "해외주식", "개별수익률": -0.030, "기여수익률": -0.012, "순자산비중": 0.40, "순비중변화": 0.0},
        {"자산군": "국내채권", "개별수익률": 0.015, "기여수익률": 0.003, "순자산비중": 0.20, "순비중변화": -0.01},
        {"자산군": "FX", "개별수익률": 0.05, "기여수익률": 0.02, "순자산비중": 0.40, "순비중변화": 0.0},
    ])


# ──────────────────────────────────────────────────────────────────
# 1. anchor schema 생성
# ──────────────────────────────────────────────────────────────────

def test_anchor_schema_basic(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors, ASSET_CLASSES_R8B, SCHEMA_VERSION,
    )
    ind = _make_indicators_csv(tmp_path)
    out = build_asset_movement_anchors(
        period="2026-04", fund_code=None,
        causal_paths=_mock_paths(),
        evidence_annotations=_mock_evidence(),
        indicators_csv_path=ind,
    )
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["period"] == "2026-04"
    assert out["fund_code"] is None
    # 8 자산군 모두 anchor 존재
    out_acs = [a["asset_class"] for a in out["asset_movements"]]
    assert sorted(out_acs) == sorted(ASSET_CLASSES_R8B)
    # anchor 마다 schema 필수 키
    for a in out["asset_movements"]:
        assert "asset_class" in a and "bm" in a and "movement_direction" in a
        assert "causal_paths" in a and "supporting_evidence_ids" in a
        assert "importance_score" in a and "movement_rank" in a


# ──────────────────────────────────────────────────────────────────
# 2. movement_direction 산출 (return / bp)
# ──────────────────────────────────────────────────────────────────

def test_movement_direction_from_indicators(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    # SP500_TR 5500→5400 → -1.8% → down
    assert by_ac["해외주식"]["movement_direction"] == "down"
    assert by_ac["해외주식"]["bm"]["return_pct"] is not None
    # USDKRW 1450→1500 → +3.4% → up
    assert by_ac["환율(FX)"]["movement_direction"] == "up"
    # GOLD 2300→2400 → up
    assert by_ac["원자재금"]["movement_direction"] == "up"
    # FED_UPPER 5.50→5.50 → flat
    assert by_ac["현금성"]["movement_direction"] == "flat"


# ──────────────────────────────────────────────────────────────────
# 3. PA / fund contribution 반영
# ──────────────────────────────────────────────────────────────────

def test_pa_fund_exposure_mapped(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path)
    pa_df = _mock_pa_dataframe()
    out = build_asset_movement_anchors(
        period="2026-04", fund_code="08N81",
        causal_paths=[], evidence_annotations=[],
        pa_asset_summary=pa_df, indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    fx = by_ac["해외주식"]["fund_exposure"]
    assert fx is not None
    assert fx["weight_pct"] == 40.0
    assert fx["contribution_pct"] == -1.2
    assert fx["individual_return_pct"] == -3.0
    # FX alias → "환율(FX)"
    assert by_ac["환율(FX)"]["fund_exposure"] is not None
    assert by_ac["환율(FX)"]["fund_exposure"]["weight_pct"] == 40.0


# ──────────────────────────────────────────────────────────────────
# 4. causal path ↔ asset matching
# ──────────────────────────────────────────────────────────────────

def test_path_to_asset_matching(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=_mock_paths(),
        evidence_annotations=[],
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    # geopolitical_oil_inflation_rates_growth → 해외주식, 원자재금, 국내채권
    overseas = by_ac["해외주식"]["causal_paths"]
    assert any(p["path_id"] == "geopolitical_oil_inflation_rates_growth"
                for p in overseas)
    # rates_domestic_bond → 국내채권
    domestic_bond = by_ac["국내채권"]["causal_paths"]
    assert any(p["path_id"] == "rates_domestic_bond" for p in domestic_bond)
    # fx_translation_overseas_assets → 환율(FX), 해외주식, 해외채권
    fx = by_ac["환율(FX)"]["causal_paths"]
    assert any(p["path_id"] == "fx_translation_overseas_assets" for p in fx)
    # gold_hedge_volatility → 원자재금
    gold = by_ac["원자재금"]["causal_paths"]
    assert any(p["path_id"] == "gold_hedge_volatility" for p in gold)


# ──────────────────────────────────────────────────────────────────
# 5. unattached evidence 생성
# ──────────────────────────────────────────────────────────────────

def test_unattached_evidence(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[],
        evidence_annotations=_mock_evidence(),
        indicators_csv_path=ind,
    )
    # ev6 (관세_무역) 와 ev1 (지정학) 은 cross-asset → unattached
    unatt_ids = [u["article_id"] for u in out["unattached_evidence"]]
    assert "ev1" in unatt_ids  # 지정학
    assert "ev6" in unatt_ids  # 관세_무역
    # 매칭 가능한 ev2/ev3/ev4/ev5 는 unattached 아님
    assert "ev2" not in unatt_ids
    assert "ev3" not in unatt_ids
    assert "ev4" not in unatt_ids
    assert "ev5" not in unatt_ids
    # ev7 unresolved 는 무시
    assert "ev7" not in unatt_ids


# ──────────────────────────────────────────────────────────────────
# 6. importance score 정렬
# ──────────────────────────────────────────────────────────────────

def test_importance_score_ordering(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_indicators_csv(tmp_path)
    out = build_asset_movement_anchors(
        period="2026-04", fund_code="08N81",
        causal_paths=_mock_paths(),
        evidence_annotations=_mock_evidence(),
        pa_asset_summary=_mock_pa_dataframe(),
        indicators_csv_path=ind,
    )
    # rank 값은 1~8
    ranks = sorted(a["movement_rank"] for a in out["asset_movements"])
    assert ranks == list(range(1, 9))
    # importance 0~1 범위
    for a in out["asset_movements"]:
        assert 0.0 <= a["importance_score"] <= 1.0
    # 큰 movement (해외주식, FX, 금) 가 작은 movement (현금성) 보다 high rank
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    assert by_ac["해외주식"]["movement_rank"] < by_ac["현금성"]["movement_rank"]
    assert by_ac["환율(FX)"]["movement_rank"] < by_ac["현금성"]["movement_rank"]


# ──────────────────────────────────────────────────────────────────
# 7. format_anchors_for_prompt 가 anchor section 포함
# ──────────────────────────────────────────────────────────────────

def test_prompt_format_contains_anchor_section(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors, format_anchors_for_prompt,
    )
    ind = _make_indicators_csv(tmp_path)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=_mock_paths(),
        evidence_annotations=_mock_evidence(),
        indicators_csv_path=ind,
    )
    text = format_anchors_for_prompt(out)
    assert "## Asset Movement Anchors" in text
    assert "[해외주식]" in text
    assert "[환율(FX)]" in text
    assert "## coverage:" in text
    # path label 노출
    assert "geopolitical" in text or "지정학" in text


# ──────────────────────────────────────────────────────────────────
# 8. raw evidence 압축 (anchor 안에는 ref id 만, 본문 inline 없음)
# ──────────────────────────────────────────────────────────────────

def test_anchor_does_not_inline_full_evidence_text(tmp_path):
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors, format_anchors_for_prompt,
    )
    ind = _make_indicators_csv(tmp_path)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=_mock_paths(),
        evidence_annotations=_mock_evidence(),
        indicators_csv_path=ind,
    )
    text = format_anchors_for_prompt(out)
    # anchor section (Unattached 이전) 안에는 evidence 본문이 inline 되지 않는다.
    # unattached 섹션은 의도적으로 title 노출 (LLM 이 매칭 실패 evidence 인지)
    if "## Unattached evidence" in text:
        anchor_section = text.split("## Unattached evidence")[0]
    else:
        anchor_section = text
    # 매칭된 evidence (ev2/3/4/5) 본문이 anchor section 에 들어가지 않음
    assert "FOMC 금리 동결, 성장주 반등" not in anchor_section
    assert "AI 빅테크 실적 호조 나스닥" not in anchor_section
    assert "원달러 환율 1500원 돌파" not in anchor_section
    assert "금 가격 안전자산 신고가" not in anchor_section


# ──────────────────────────────────────────────────────────────────
# 9. agent JSON schema instruction 에 asset_movement_commentary 등장
# ──────────────────────────────────────────────────────────────────

def test_agent_prompt_schema_includes_amc():
    """debate_engine._build_agent_prompt 가 asset_movement_commentary 키를 schema 안내에 포함."""
    from market_research.report.debate_engine import _build_agent_prompt
    ctx = {
        "year": 2026, "month": 4, "fund_code": None,
        "news_summary_text": "(none)", "indicators_text": "(none)",
        "timeseries_narrative_text": "", "graph_paths_text": "",
        "wiki_context_text": "", "asset_coverage_text": "",
        "asset_movement_anchors_text": "## Asset Movement Anchors (R8-B)\n[해외주식] ...",
    }
    p = _build_agent_prompt("monygeek", ctx)
    assert "asset_movement_commentary" in p
    assert "Asset Movement Anchors" in p
    assert "## 2026년 4월 시장 분석" in p


# ──────────────────────────────────────────────────────────────────
# 10. fund_comment_service _market_comment_to_inputs 가 amc 통과
# ──────────────────────────────────────────────────────────────────

def test_fund_comment_passes_asset_movement_commentary():
    from market_research.report.fund_comment_service import (
        _market_comment_to_inputs,
    )
    payload = {
        "final_comment": "본문",
        "asset_movement_commentary": [
            {"asset_class": "해외주식", "past_movement": "-3.0%",
             "drivers": ["성장주조정"], "outlook": "리스크 잔존",
             "portfolio_implication": "비중축소"}
        ],
        "asset_movement_anchors": {"asset_movements": [...]},
    }
    inputs = _market_comment_to_inputs(payload)
    assert "asset_movement_commentary" in inputs
    assert "asset_movement_anchors" in inputs
    assert inputs["asset_movement_commentary"][0]["asset_class"] == "해외주식"


# ──────────────────────────────────────────────────────────────────
# 11. build_report_prompt 가 asset_movement section inline
# ──────────────────────────────────────────────────────────────────

def test_build_report_prompt_inline_amc():
    from market_research.report import comment_engine
    inputs = {
        "market_view": "시장",
        "asset_movement_commentary": [
            {"asset_class": "해외주식", "past_movement": "-3.0%",
             "drivers": ["성장주조정", "금리"], "outlook": "리스크 잔존",
             "portfolio_implication": "비중축소"}
        ],
    }
    data_ctx = {"bm": {}, "fund_ret": None, "pa": {},
                "holdings_end": {}, "holdings_diff": [], "price_patterns": {}}
    p = comment_engine.build_report_prompt("08K88", 2026, 1, data_ctx, inputs)
    assert "자산군별 시장 movement (debate 결과)" in p
    assert "[해외주식]" in p
    assert "성장주조정" in p
    assert "비중축소" in p


# ──────────────────────────────────────────────────────────────────
# 12. comment_trace.build_trace 에 anchor + commentary surface
# ──────────────────────────────────────────────────────────────────

def _write_trace_inputs(tmp_path: Path, period: str, fund: str,
                          fund_draft_payload: dict,
                          market_source_payload: dict):
    pdir = tmp_path / "market_research" / "data" / "report_output" / period
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{fund}.draft.json").write_text(
        json.dumps(fund_draft_payload, ensure_ascii=False), encoding="utf-8")
    (pdir / "_market.draft.json").write_text(
        json.dumps(market_source_payload, ensure_ascii=False), encoding="utf-8")


def test_comment_trace_surfaces_asset_movement(tmp_path, monkeypatch):
    import importlib
    import tools.comment_trace as ct
    importlib.reload(ct)
    monkeypatch.setattr(ct, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ct, "REPORT_OUTPUT_DIR",
                        tmp_path / "market_research" / "data" / "report_output")
    monkeypatch.setattr(ct, "INCIDENTS_DIR", tmp_path / "debug" / "incidents")

    fund_draft = {
        "fund_code": "08N81", "period": "2026-04",
        "report_type": "fund", "status": "draft",
        "debate_run_id": "RUN_R8B",
        "draft_comment": "본문",
        "evidence_annotations": _mock_evidence(),
        "data_snapshot": {"fund_return": 1.2, "pa_classes": ["해외주식"],
                          "holdings_top3": [], "trades": {}, "bm_count": 5},
        "inputs_used": {},
    }
    market = {
        "asset_movement_anchors": {
            "schema_version": "r8b-asset-movement-anchor-1.0.0",
            "asset_movements": [{"asset_class": "해외주식",
                                  "movement_rank": 1,
                                  "importance_score": 0.6}],
        },
        "asset_movement_commentary": [
            {"asset_class": "해외주식", "past_movement": "-3%",
             "drivers": ["성장주"], "outlook": "리스크",
             "portfolio_implication": "축소"}
        ],
    }
    _write_trace_inputs(tmp_path, "2026-04", "08N81", fund_draft, market)
    trace = ct.build_trace("2026-04", "08N81", market_source_mode="auto")
    assert trace.get("asset_movement_anchors") is not None
    assert (trace["asset_movement_anchors"]["schema_version"]
            == "r8b-asset-movement-anchor-1.0.0")
    assert isinstance(trace.get("asset_movement_commentary"), list)
    assert trace["asset_movement_commentary"][0]["asset_class"] == "해외주식"


# ──────────────────────────────────────────────────────────────────
# 13. 기존 R6-A / R7 회귀 — graph_seed + graph_seed_causal 동시 존재
# ──────────────────────────────────────────────────────────────────

def test_existing_r6a_r7_compat(tmp_path, monkeypatch):
    """R8-B 가 추가됐어도 기존 graph_seed (R5-B provenance) + graph_seed_causal (R7) 동시 존재."""
    import importlib
    import tools.comment_trace as ct
    importlib.reload(ct)
    monkeypatch.setattr(ct, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ct, "REPORT_OUTPUT_DIR",
                        tmp_path / "market_research" / "data" / "report_output")
    monkeypatch.setattr(ct, "INCIDENTS_DIR", tmp_path / "debug" / "incidents")

    fund_draft = {
        "fund_code": "07G04", "period": "2026-04",
        "report_type": "fund", "status": "draft",
        "draft_comment_raw": "■ 시장\n[ref:1] 본문.",
        "draft_comment": "■ 시장\n본문.",
        "evidence_annotations": _mock_evidence(),
        "data_snapshot": {"fund_return": None, "pa_classes": [],
                          "holdings_top3": [], "trades": {}, "bm_count": 0},
        "inputs_used": {},
    }
    pdir = tmp_path / "market_research" / "data" / "report_output" / "2026-04"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "07G04.draft.json").write_text(
        json.dumps(fund_draft, ensure_ascii=False), encoding="utf-8")
    trace = ct.build_trace("2026-04", "07G04", market_source_mode="auto")
    assert "graph_seed" in trace
    assert "graph_seed_causal" in trace
    assert trace["graph_seed"]["nodes"]
    assert trace["graph_seed_causal"]["nodes"]


def test_load_indicator_changes_sparse_weekend_last_row(tmp_path):
    """월말(5/31)이 주말이라 마지막 row 시장 컬럼이 빈값이어도,
    컬럼별 last-valid(5/29) 값으로 return_pct 가 계산되어야 한다.
    (리터럴 last row 사용 시 전 자산군 null 이 되던 버그 회귀 방지.)"""
    from market_research.report.asset_movement_anchor import load_indicator_changes

    csv_text = (
        "date,USDKRW,SP500_TR,MSCI_KOREA,GOLD,FED_UPPER,KAP_BOND_TR,HY_TR,UST_7_10Y_TR\n"
        "2026-04-30,1480.0,1140.0,200.0,4600.0,3.75,272.0,2940.0,178.0\n"
        "2026-05-29,1507.0,1200.0,250.0,4545.0,3.75,269.0,2960.0,180.0\n"
        "2026-05-30,,,,,3.75,,,\n"   # 주말 — 시장 컬럼 빈값, 정책금리만 채워짐
        "2026-05-31,,,,,3.75,,,\n"
    )
    fp = tmp_path / "indicators.csv"
    fp.write_text(csv_text, encoding="utf-8")

    asset_bm, warns = load_indicator_changes("2026-05", fp)

    # 국내주식: (250-200)/200 = +25.0% (5/29 last-valid, 5/31 빈값 무시)
    assert "국내주식" in asset_bm, f"국내주식 missing — warns={warns}"
    assert asset_bm["국내주식"]["return_pct"] == 25.0
    assert asset_bm["국내주식"]["level_end"] == 250.0
    # 해외주식도 정상
    assert abs(asset_bm["해외주식"]["return_pct"] - ((1200 - 1140) / 1140 * 100)) < 1e-3
    # 시장 자산군이 빈 last row 때문에 missing 되지 않아야 함
    assert "국내주식 (MSCI_KOREA) missing in 2026-05" not in warns
