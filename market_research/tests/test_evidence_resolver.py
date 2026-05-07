"""R8-A 회귀: evidence_resolver multi-source lookup.

LLM 호출 0. tmp_path 만 사용 — 운영 데이터 무접근.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _setup_debate_logs(tmp: Path, period: str, anns: list[dict]) -> None:
    p = tmp / "market_research" / "data" / "debate_logs"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{period}.json").write_text(
        json.dumps({"evidence_annotations": anns}, ensure_ascii=False),
        encoding="utf-8")


def _setup_news(tmp: Path, year: int, month: int, articles: list[dict]) -> None:
    p = tmp / "market_research" / "data" / "news"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{year}-{month:02d}.json").write_text(
        json.dumps({"articles": articles}, ensure_ascii=False),
        encoding="utf-8")


def _setup_research(tmp: Path, year: int, month: int, articles: list[dict]) -> None:
    p = tmp / "market_research" / "data" / "naver_research" / "adapted"
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{year}-{month:02d}.json").write_text(
        json.dumps(articles, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
# Period parsing
# ──────────────────────────────────────────────────────────────────

def test_period_to_months_quarter():
    from tools.evidence_resolver import _period_to_months
    yr, prim, buf = _period_to_months("2026-Q1")
    assert yr == 2026
    assert prim == [1, 2, 3]
    # buffer = ±1 → [1,2,3,4]  (lo clamp 1, hi=4)
    assert buf == [1, 2, 3, 4]


def test_period_to_months_monthly():
    from tools.evidence_resolver import _period_to_months
    yr, prim, buf = _period_to_months("2026-04")
    assert yr == 2026
    assert prim == [4]
    assert buf == [3, 4, 5]


def test_period_to_months_unknown():
    from tools.evidence_resolver import _period_to_months
    yr, prim, buf = _period_to_months("garbage")
    assert prim == [] and buf == []


# ──────────────────────────────────────────────────────────────────
# Lookup priority
# ──────────────────────────────────────────────────────────────────

def test_resolver_p3_debate_logs(tmp_path):
    """fund_draft 와 market_source 가 비어도 debate_logs 에 있으면 복구."""
    from tools.evidence_resolver import resolve_evidence_annotations
    _setup_debate_logs(tmp_path, "2026-Q1", [
        {"article_id": "A1", "title": "Iran oil", "source": "Reuters",
         "date": "2026-01-15", "topic": "지정학", "all_topics": ["지정학"]},
        {"article_id": "A2", "title": "FOMC rate", "source": "WSJ",
         "date": "2026-02-20", "topic": "금리_채권"},
    ])
    anns, stats = resolve_evidence_annotations(
        ["A1", "A2"], "2026-Q1", None, None, tmp_path,
    )
    assert stats["resolved_count"] == 2
    assert stats["unresolved_count"] == 0
    assert stats["resolution_rate"] == 1.0
    assert stats["source_counts"]["debate_logs"] == 2
    assert anns[0]["title"] == "Iran oil"
    assert anns[0]["_source_type"] == "debate_logs"
    assert anns[0]["_resolved"] is True


def test_resolver_p1_fund_draft_takes_priority(tmp_path):
    """fund_draft 에 있으면 P3 debate_logs 보다 우선 (fund_draft 는 가장 최신)."""
    from tools.evidence_resolver import resolve_evidence_annotations
    _setup_debate_logs(tmp_path, "2026-Q1", [
        {"article_id": "A1", "title": "OLD title from debate_logs",
         "source": "Old"},
    ])
    fund_draft = {"evidence_annotations": [
        {"article_id": "A1", "title": "NEW title from fund_draft",
         "source": "New"},
    ]}
    anns, stats = resolve_evidence_annotations(
        ["A1"], "2026-Q1", fund_draft, None, tmp_path,
    )
    assert anns[0]["title"] == "NEW title from fund_draft"
    assert anns[0]["_source_type"] == "fund_draft"
    assert stats["source_counts"]["fund_draft"] == 1


def test_resolver_p4_news_fallback(tmp_path):
    """debate_logs 없고 news/{YYYY-MM}.json 에 있으면 복구."""
    from tools.evidence_resolver import resolve_evidence_annotations
    _setup_news(tmp_path, 2026, 2, [
        {"_article_id": "A1", "title": "BTC up", "source": "Bloomberg",
         "primary_topic": "macro", "url": "http://x"},
    ])
    anns, stats = resolve_evidence_annotations(
        ["A1"], "2026-Q1", None, None, tmp_path,
    )
    assert stats["source_counts"]["news"] == 1
    assert anns[0]["title"] == "BTC up"
    assert anns[0]["url"] == "http://x"


def test_resolver_p5_research_fallback(tmp_path):
    """news 도 없으면 naver_research adapted 에서."""
    from tools.evidence_resolver import resolve_evidence_annotations
    _setup_research(tmp_path, 2026, 1, [
        {"_article_id": "A1", "title": "신한 FX Check-up",
         "source": "신한투자증권", "primary_topic": "환율_FX"},
    ])
    anns, stats = resolve_evidence_annotations(
        ["A1"], "2026-Q1", None, None, tmp_path,
    )
    assert stats["source_counts"]["research"] == 1
    assert anns[0]["title"] == "신한 FX Check-up"
    assert anns[0]["source"] == "신한투자증권"


def test_resolver_buffered_month(tmp_path):
    """primary_months 에 없어도 buffered_months 에서 발견."""
    from tools.evidence_resolver import resolve_evidence_annotations
    # 2026-Q1 buffer = [1,2,3,4]. 4월에만 article 두기.
    _setup_news(tmp_path, 2026, 4, [
        {"_article_id": "A1", "title": "April spillover", "source": "X"},
    ])
    anns, stats = resolve_evidence_annotations(
        ["A1"], "2026-Q1", None, None, tmp_path,
    )
    assert stats["source_counts"]["news"] == 1
    assert anns[0]["title"] == "April spillover"


def test_resolver_unresolved_placeholder(tmp_path):
    """어디에도 없으면 placeholder + unresolved_count."""
    from tools.evidence_resolver import resolve_evidence_annotations, UNRESOLVED_TITLE
    anns, stats = resolve_evidence_annotations(
        ["MISSING1", "MISSING2"], "2026-Q1", None, None, tmp_path,
    )
    assert stats["resolved_count"] == 0
    assert stats["unresolved_count"] == 2
    assert stats["resolution_rate"] == 0.0
    assert stats["unresolved_ids"] == ["MISSING1", "MISSING2"]
    assert anns[0]["title"] == UNRESOLVED_TITLE
    assert anns[0]["_resolved"] is False
    assert anns[0]["_source_type"] == "unresolved"


def test_resolver_partial(tmp_path):
    """일부 resolved + 일부 unresolved 가 섞임."""
    from tools.evidence_resolver import resolve_evidence_annotations
    _setup_debate_logs(tmp_path, "2026-Q1", [
        {"article_id": "A1", "title": "found", "source": "S"},
    ])
    anns, stats = resolve_evidence_annotations(
        ["A1", "MISSING"], "2026-Q1", None, None, tmp_path,
    )
    assert stats["resolved_count"] == 1
    assert stats["unresolved_count"] == 1
    assert stats["resolution_rate"] == 0.5
    assert anns[0]["_resolved"] is True
    assert anns[1]["_resolved"] is False


def test_is_resolved_helper():
    from tools.evidence_resolver import is_resolved, UNRESOLVED_TITLE
    assert is_resolved({"title": "Real", "_resolved": True}) is True
    assert is_resolved({"title": UNRESOLVED_TITLE, "_resolved": False}) is False
    assert is_resolved({"title": ""}) is False
    assert is_resolved({"title": "ok"}) is True
    assert is_resolved(None) is False


# ──────────────────────────────────────────────────────────────────
# Causal graph 통합 — unresolved evidence skip
# ──────────────────────────────────────────────────────────────────

def test_causal_graph_skips_unresolved_evidence():
    """resolved=False 이면 claim extraction 안함, [unresolved] warning 만 발생."""
    from tools.causal_graph import build_causal_layer
    ea = [
        {"ref": 1, "article_id": "A1", "title": "이란 분쟁 유가 상승",
         "source": "Reuters", "date": "2026-01-15", "_resolved": True},
        {"ref": 2, "article_id": "A2", "title": "(매핑 실패)",
         "source": "", "date": "", "_resolved": False},
    ]
    layer = build_causal_layer(ea, [], "08N81", "2026-Q1")
    # A1 만 claim 생성, A2 는 skip
    assert len(layer["causal_claims"]) == 1
    assert layer["causal_claims"][0]["source_evidence_id"] == "A1"
    # warning 분류
    ws = layer["warnings"]
    has_unresolved = any("[unresolved]" in w for w in ws)
    has_no_topic_for_a2 = any(
        ("no topic matched" in w or "no_topic_matched" in w) and "A2" in w
        for w in ws
    )
    assert has_unresolved, f"expected [unresolved] warning, got: {ws}"
    assert not has_no_topic_for_a2, "should not emit no_topic warning for unresolved evidence"


def test_causal_graph_no_topic_warning_only_for_resolved():
    """resolved 이지만 토픽 매칭 안되는 evidence → [no_topic_matched] warning."""
    from tools.causal_graph import build_causal_layer
    ea = [
        {"ref": 1, "article_id": "A1", "title": "회사 ABC 분기 실적 발표",
         "source": "Dart", "date": "2026-01-15", "_resolved": True},
    ]
    layer = build_causal_layer(ea, [], "08N81", "2026-Q1")
    ws = layer["warnings"]
    assert any("[no_topic_matched]" in w for w in ws)
    assert not any("[unresolved]" in w for w in ws)
