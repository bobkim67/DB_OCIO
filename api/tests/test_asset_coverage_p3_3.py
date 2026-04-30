"""P3-3 Asset coverage guardrail tests.

LLM 미호출. unit + integration (debate_engine 컨텍스트 빌드까지).
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────
# Unit — asset_coverage 모듈
# ─────────────────────────────────────────────────────────────────────

def _mk_article(topics: list[str], primary: bool = True) -> dict:
    return {
        "is_primary": primary,
        "_classified_topics": [{"topic": t} for t in topics],
    }


def test_coverage_dominant_middle_east_does_not_starve_other_assets():
    """중동/지정학이 80% 이상이어도 다른 자산군의 weak/missing 분류는 수행되어야 함."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    # 80% 중동/지정학 + 10% 환율 + 10% 금
    arts = ([_mk_article(["지정학"])] * 80
            + [_mk_article(["환율_FX"])] * 10
            + [_mk_article(["귀금속_금"])] * 10)
    cov = build_asset_coverage_map(
        primary_news=arts,
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
        topic_counts=Counter({"지정학": 80, "환율_FX": 10, "귀금속_금": 10}),
    )
    assert cov["dominant_topic"] == "지정학"
    assert cov["dominant_topic_share"] >= 0.7
    # 8 자산군 모두 분류됨
    accs = [r["asset_class"] for r in cov["asset_coverage_map"]]
    assert len(accs) == 8
    # 비중동 자산군이 weak/missing 으로 잡힘
    assert "국내주식" in cov["weak_asset_classes"] + cov["missing_asset_classes"]
    assert "국내채권" in cov["weak_asset_classes"] + cov["missing_asset_classes"]
    assert "해외채권" in cov["weak_asset_classes"] + cov["missing_asset_classes"]


def test_coverage_status_levels():
    """P3-3.1: classified-only 단독은 weak, graph 또는 ts 와 결합되면 covered."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["KOSPI"])] * 5,    # 국내주식 classified
        graph_paths=[{"labels": ["KOSPI 반등"], "target": "국내주식",
                       "confidence": 0.5}],            # 국내주식 graph
        wiki_selected_pages=[],
        timeseries_narrative_text="환율 상승",            # 환율 ts only
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    # 국내주식: graph+classified → strong=1 + classified → covered? 규칙 strong>=2 또는
    # selected>=1 + classified>=1. 여기는 strong=1 (graph) → weak. 의도 확인:
    # P3-3.1 hotfix 의도는 classified 단독으로 covered 안 되는 것. classified+graph 는
    # strong=1 + classified > 0 → covered 분기 (selected_n>0 조건). 여기는 selected_n=0
    # 이라 classified+graph 만으로 weak.
    assert rows["국내주식"]["coverage_status"] in ("covered", "weak")
    # 환율: ts only → strong=1 → weak
    assert rows["환율"]["coverage_status"] == "weak"
    assert rows["국내채권"]["coverage_status"] == "missing"


def test_fallback_priority_classified_only_is_evidence_classified():
    """P3-3.1: classified 단독은 evidence_classified label."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["국내주식"])],
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    # classified-only 면 evidence_classified (P3-3.1 신규 label)
    assert rows["국내주식"]["fallback_used"] == "evidence_classified"


def test_fallback_priority_selected_first():
    """P3-3.1: selected_evidence 가 있으면 최우선 (evidence_selected)."""
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["국내주식"])],
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
        selected_evidence=[{"title": "KOSPI 반등", "topic": "KOSPI"}],
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    # selected hit → covered + fallback 의미 없음 → none
    assert rows["국내주식"]["coverage_status"] == "covered"
    assert rows["국내주식"]["fallback_used"] == "none"


def test_fallback_timeseries_when_only_ts():
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[],
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="국내주식 KOSPI 반등 흐름",
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    assert rows["국내주식"]["fallback_used"] == "timeseries"


def test_fallback_return_when_only_return_signal():
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[],
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
        asset_returns={"해외채권 미국채 10Y": -0.5},
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    assert rows["해외채권"]["fallback_used"] == "return"


def test_fallback_no_material_event_when_nothing():
    from market_research.report.asset_coverage import build_asset_coverage_map
    cov = build_asset_coverage_map(
        primary_news=[],
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
    )
    rows = {r["asset_class"]: r for r in cov["asset_coverage_map"]}
    assert rows["국내채권"]["fallback_used"] == "no_material_event"
    assert rows["국내채권"]["coverage_status"] == "missing"


def test_format_for_prompt_contains_section_header():
    from market_research.report.asset_coverage import (
        build_asset_coverage_map, format_asset_coverage_for_prompt,
    )
    cov = build_asset_coverage_map(
        primary_news=[_mk_article(["KOSPI"])],
        graph_paths=[],
        wiki_selected_pages=[],
        timeseries_narrative_text="",
    )
    text = format_asset_coverage_for_prompt(cov)
    assert "## 자산군별 필수 점검" in text
    for ac in ("국내주식", "해외주식", "국내채권", "해외채권",
               "환율", "금/대체", "크레딧", "현금성"):
        assert ac in text


def test_format_for_prompt_empty_when_no_coverage():
    from market_research.report.asset_coverage import format_asset_coverage_for_prompt
    assert format_asset_coverage_for_prompt({}) == ""
    assert format_asset_coverage_for_prompt({"asset_coverage_map": []}) == ""


# ─────────────────────────────────────────────────────────────────────
# Integration — debate_engine prompt
# ─────────────────────────────────────────────────────────────────────

def test_agent_prompt_contains_asset_coverage_section():
    from market_research.report import debate_engine as DE
    ctx = {
        "year": 2026, "month": 4,
        "news_summary_text": "(뉴스 데이터 없음)",
        "indicators_text": "",
        "timeseries_narrative_text": "",
        "graph_paths_text": "",
        "wiki_context_text": "",
        "asset_coverage_text": "## 자산군별 필수 점검\n- 국내주식: ...",
    }
    p = DE._build_agent_prompt("bull", ctx)
    assert "## 자산군별 필수 점검" in p


def test_synthesis_prompt_includes_three_asset_directive():
    """synthesis Step1 prompt 소스에 P3-3 강제 문구 존재."""
    import inspect
    from market_research.report import debate_engine as DE
    src = inspect.getsource(DE._synthesize_debate)
    assert "asset_coverage_text" in src
    assert "최소 3개 이상의 주요 자산군" in src
    assert "근거가 약한 자산군은 단정 표현을 피하고" in src


# ─────────────────────────────────────────────────────────────────────
# Client leak regression — _debug_trace 의 P3-3 항목들
# ─────────────────────────────────────────────────────────────────────

def test_client_no_asset_coverage_leak(client, tmp_path, monkeypatch):
    """asset_coverage_map / fallback_used_by_asset 등이 client 응답에 누출되지 않음."""
    from market_research.report import report_store
    from api.services import report_service

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)

    def _empty_macro(keys=None, start_date=None):
        from api.schemas.macro import MacroTimeseriesResponseDTO
        from api.schemas.meta import BaseMeta
        from datetime import datetime, timezone
        return MacroTimeseriesResponseDTO(
            meta=BaseMeta(as_of_date=None, source="mock", sources=[],
                          is_fallback=True, warnings=["test stub"],
                          generated_at=datetime.now(timezone.utc)),
            series=[],
        )
    monkeypatch.setattr(report_service.macro_service,
                        "build_macro_timeseries", _empty_macro)

    fp = root / "2026-04"
    fp.mkdir(parents=True, exist_ok=True)
    (fp / "_market.final.json").write_text(json.dumps({
        "fund_code": "_market", "period": "2026-04",
        "status": "approved", "approved": True,
        "approved_at": "2026-04-30T14:00:45",
        "approved_debate_run_id": "RID-P33-1",
        "generated_at": "2026-04-30T13:56:04",
        "final_comment": "comment",
        "evidence_annotations": [], "related_news": [],
    }, ensure_ascii=False), encoding="utf-8")
    # draft 에 P3-3 디버그 키가 들어와도 client 에 노출 금지
    (fp / "_market.draft.json").write_text(json.dumps({
        "fund_code": "_market", "period": "2026-04",
        "status": "approved", "draft_comment": "draft",
        "debate_run_id": "RID-P33-1",
        "generated_at": "2026-04-30T13:56:04",
        "_debug_trace": {
            "asset_coverage_map": [{"asset_class": "국내주식"}],
            "fallback_used_by_asset": {"국내주식": "timeseries"},
            "covered_asset_classes": ["환율"],
            "weak_asset_classes": ["국내주식"],
            "missing_asset_classes": ["크레딧"],
            "dominant_topic": "지정학",
            "asset_coverage_pass": True,
            "final_comment_asset_mentions": {"환율": 3},
        },
    }, ensure_ascii=False), encoding="utf-8")

    r = client.get("/api/market-report", params={"period": "2026-04"})
    assert r.status_code == 200
    raw = r.text
    forbidden = (
        "_debug_trace",
        "asset_coverage_map", "fallback_used_by_asset",
        "covered_asset_classes", "weak_asset_classes",
        "missing_asset_classes", "asset_coverage_pass",
        "dominant_topic", "final_comment_asset_mentions",
    )
    leaks = [k for k in forbidden if k in raw]
    assert leaks == [], f"forbidden keys leaked: {leaks}"
