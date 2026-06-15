# -*- coding: utf-8 -*-
"""Research claim extractor + monygeek adapter 단위 테스트 (P1/P2). LLM 0(fake)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.collect.monygeek_research_adapter import to_article_like  # noqa: E402
from market_research.analyze.research_claim_extractor import (  # noqa: E402
    build_research_extraction_prompt,
    extract_research_claims,
    _resolve_broker_author,
)


def _fake_claim_json() -> str:
    return json.dumps([{
        "claim_text": "반도체 업황 회복 기대로 국내주식 강세 전망",
        "claim_type": "outlook_view", "stance": "bullish", "view": "반도체 비중확대",
        "rationale_text": "AI capex 지속 + 메모리 가격 반등", "risk_factor": "중국 수요 둔화",
        "affected_assets": [{"asset_class": "국내주식", "direction": "positive",
                             "confidence": 0.8, "role": "primary"}],
        "primary_asset": "국내주식", "regions": ["KR"], "sectors": ["테크_AI_반도체"],
        "causal_chain": [{"source": "AI capex", "target": "반도체 실적",
                          "relation": "supports"}],
        "direction": "positive", "horizon": "medium", "confidence": 0.8, "salience": 0.7,
        "supporting_evidence_ids": ["aid001"], "counter_evidence_ids": [],
    }])


def _ev() -> list[dict]:
    return [{"_article_id": "aid001", "title": "반도체 전망", "source": "미래에셋증권",
             "date": "2026-05-10", "description": "AI 슈퍼사이클"}]


# ── P1: monygeek adapter ──

def test_monygeek_to_article_like_schema():
    post = {"title": "[48시간뉴스] 유동성 재편", "date": "2026-05-12",
            "content": "본문...", "url": "http://x", "log_no": "123",
            "blog_category": "경제"}
    a = to_article_like(post)
    assert a["source_type"] == "monygeek"
    assert a["source"] == "monygeek"
    assert a["description"] == "본문..."
    assert len(a["_article_id"]) == 12          # MD5 12 hex
    assert a["_raw_log_no"] == "123"


def test_monygeek_article_id_deterministic():
    post = {"title": "T", "date": "2026-05-01", "content": "c"}
    assert to_article_like(post)["_article_id"] == to_article_like(post)["_article_id"]


# ── P2: research extraction ──

def test_research_prompt_includes_stance_and_taxonomy():
    p = build_research_extraction_prompt("2026-05", _ev(), source_type="naver_research")
    assert "stance" in p["user"]
    assert "bullish" in p["user"]
    assert "source_type=naver_research" in p["user"]
    assert p["model"].startswith("claude-haiku")


def test_extract_research_claims_fake_llm_valid():
    r = extract_research_claims("2026-05", _ev(), source_type="naver_research",
                                llm_call=lambda _p: _fake_claim_json())
    assert len(r["claims"]) == 1
    c = r["claims"][0]
    assert c["stance"] == "bullish"
    assert c["source_type"] == "naver_research"
    assert c["broker_author"] == "미래에셋증권"   # evidence 에서 해석
    assert c["view"] == "반도체 비중확대"
    assert c["primary_asset"] == "국내주식"


def test_extract_research_empty_evidence():
    r = extract_research_claims("2026-05", [], source_type="monygeek",
                                llm_call=lambda _p: "[]")
    assert r["abort_reason"] == "no_evidence"
    assert r["claims"] == []


def test_extract_research_parse_failure_graceful():
    r = extract_research_claims("2026-05", _ev(), source_type="naver_research",
                                llm_call=lambda _p: "not json at all")
    assert r["abort_reason"] == "json_parse_failed"
    assert r["claims"] == []


def test_resolve_broker_author_multi():
    ev_index = {"a": {"source": "키움증권"}, "b": {"source": "미래에셋증권"}}
    claim = {"supporting_evidence_ids": ["a", "b", "a"]}
    assert _resolve_broker_author(claim, ev_index) == "키움증권 / 미래에셋증권"
