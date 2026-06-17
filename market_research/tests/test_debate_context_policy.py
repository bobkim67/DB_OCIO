# -*- coding: utf-8 -*-
"""debate_context_policy 단위 테스트 (Phase 1, DB/LLM 비의존)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.report.debate_context_policy import (  # noqa: E402
    LEGACY_POLICY, RESEARCH_ONLY_POLICY, RESEARCH_WIKI_DIRS,
    resolve_policy, summarize_prompt_sections, active_sections,
    validate_research_only_clean, RESEARCH_ONLY_FORBIDDEN,
)


def test_legacy_preset_all_sources_on():
    p = LEGACY_POLICY
    assert p.news_summary_enabled and p.news_evidence_lane_enabled
    assert p.graph_paths_enabled and p.wiki_keyword_retriever_enabled
    assert p.research_wiki_enabled and p.macro_indicators_enabled
    assert p.monygeek_blog_enabled
    assert p.research_synthesis_enabled is False     # 09 는 Phase 2
    assert p.operational_claims_enabled is True       # legacy 는 R9-A claim 유지
    assert p.wiki_context_pack_dirs is None          # stage default 전체


def test_research_only_preset_blocks_news_graph_retriever():
    p = RESEARCH_ONLY_POLICY
    assert p.news_summary_enabled is False
    assert p.news_evidence_lane_enabled is False
    assert p.graph_paths_enabled is False
    assert p.wiki_keyword_retriever_enabled is False
    # 유지되는 소스
    assert p.research_wiki_enabled and p.research_synthesis_enabled
    assert p.macro_indicators_enabled and p.monygeek_blog_enabled
    # context pack dir = research dir 만, news-derived(01/02/07) 제외
    assert p.wiki_context_pack_dirs == RESEARCH_WIKI_DIRS
    for d in ("01_Events", "02_Entities", "07_Graph_Evidence"):
        assert d not in RESEARCH_WIKI_DIRS
    # Phase 2.7 — 08_Claims(뉴스 트랙) 제외, 09 §4/§5 원자 claim 으로 대체
    assert "08_Claims" not in RESEARCH_WIKI_DIRS
    assert "08_Claims" not in p.wiki_context_pack_dirs
    assert p.research_synthesis_include_claims is True
    assert p.operational_claims_enabled is False      # R9-A 뉴스-트랙 claim 도 제외


def test_resolve_policy_modes():
    assert resolve_policy("legacy") is LEGACY_POLICY
    assert resolve_policy("research_only") is RESEARCH_ONLY_POLICY
    # 기존 research_only=True backward-compat: news lane 만 차단, 나머지 legacy
    r = resolve_policy("legacy", research_only=True)
    assert r.name == "legacy_research_lane_only"
    assert r.news_evidence_lane_enabled is False
    assert r.news_summary_enabled is True       # full research-only 와 구분
    assert r.graph_paths_enabled is True


def test_resolve_policy_unknown_mode():
    import pytest
    with pytest.raises(ValueError):
        resolve_policy("bogus")


def test_summarize_and_active_sections():
    ctx = {
        "news_summary_text": "뉴스",
        "graph_paths_text": "",
        "research_synthesis_text": "09 합성",
        "wiki_context_text": "   ",          # whitespace → 0
    }
    sizes = summarize_prompt_sections(ctx)
    assert sizes["news_summary"] == len("뉴스")
    assert sizes["graph_paths"] == 0
    assert sizes["wiki_keyword_retriever"] == 0
    act = active_sections(ctx)
    assert "news_summary" in act and "research_synthesis" in act
    assert "graph_paths" not in act and "wiki_keyword_retriever" not in act


def test_validate_research_only_clean_pass():
    # 금지 소스 전부 비어있음 → clean
    ctx = {"research_synthesis_text": "09", "news_summary_text": "",
           "graph_paths_text": "", "wiki_context_text": ""}
    ok, viol = validate_research_only_clean(ctx)
    assert ok is True and viol == []


def test_validate_research_only_clean_detects_leak():
    ctx = {"news_summary_text": "뉴스 분류 요약 ...", "graph_paths_text": "경로"}
    ok, viol = validate_research_only_clean(ctx)
    assert ok is False
    assert "news_summary" in viol and "graph_paths" in viol
    assert set(viol).issubset(set(RESEARCH_ONLY_FORBIDDEN))
