"""R7 회귀: tools/causal_graph + comment_trace 통합.

LLM 호출 0. DB 의존 0. 디스크: tmp_path 만 사용 (실 운영 wiki 미접근).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────
# Mock evidence (08N81 시나리오)
# ──────────────────────────────────────────────────────────────────

def _mock_evidence_08n81() -> list[dict]:
    return [
        {"ref": 1, "article_id": "ev1",
         "title": "이란 분쟁 격화로 유가 100달러 돌파", "source": "Reuters",
         "date": "2026-01-15", "topic": "지정학", "all_topics": ["지정학"]},
        {"ref": 2, "article_id": "ev2",
         "title": "WGBI 편입으로 외국인 국채 수급 강세 전망",
         "source": "Bloomberg", "date": "2026-01-20",
         "topic": "금리_채권", "all_topics": ["금리_채권"]},
        {"ref": 3, "article_id": "ev3",
         "title": "FOMC 금리 동결 결정, 성장주 반등", "source": "WSJ",
         "date": "2026-02-22", "topic": "금리_채권"},
        {"ref": 4, "article_id": "ev4",
         "title": "AI 빅테크 실적 호조로 나스닥 사상 최고",
         "source": "FT", "date": "2026-02-25"},
        {"ref": 5, "article_id": "ev5",
         "title": "원달러 환율 1500원 돌파, 해외자산 환산 손실 확대",
         "source": "한경", "date": "2026-03-28"},
        {"ref": 6, "article_id": "ev6",
         "title": "금 가격 안전자산 선호로 신고가 경신",
         "source": "연합뉴스", "date": "2026-03-30"},
        {"ref": 7, "article_id": "ev7",
         "title": "인플레이션 둔화 기대로 채권 강세 지속",
         "source": "Reuters", "date": "2026-03-02"},
        # rule 매칭 안되는 항목 (no-content warning 검증)
        {"ref": 8, "article_id": "ev8",
         "title": "회사 ABC 분기 실적 발표 예정", "source": "DartReport",
         "date": "2026-03-05"},
    ]


def _mock_attributions() -> list[dict]:
    """section_attribution mock — ev1/ev3 가 market_review section 에 묶임."""
    return [
        {"section_id": "00_market_review", "section_title": "시장 평가",
         "attribution_method": "explicit_ref", "ref_ids": [1, 3],
         "evidence_ids": ["ev1", "ev3"],
         "asset_classes_mentioned": [], "fund_data_keys": [], "warnings": []},
        {"section_id": "01_outlook", "section_title": "전망",
         "attribution_method": "explicit_ref", "ref_ids": [2, 7],
         "evidence_ids": ["ev2", "ev7"],
         "asset_classes_mentioned": [], "fund_data_keys": [], "warnings": []},
    ]


# ──────────────────────────────────────────────────────────────────
# 1. Evidence content loader
# ──────────────────────────────────────────────────────────────────

def test_evidence_content_loader_basic():
    from tools.causal_graph import load_evidence_content
    contents, w = load_evidence_content(_mock_evidence_08n81())
    assert len(contents) == 8
    c0 = contents[0]
    assert c0["evidence_id"] == "ev1"
    assert c0["title"].startswith("이란")
    assert c0["source"] == "Reuters"
    assert c0["month"] == "2026-01"
    assert c0["has_body"] is False  # news_dir 없음 → body 미보강
    assert c0["linked_sections"] == []


def test_evidence_content_loader_linked_sections():
    """attribution 의 evidence_id 가 linked_section_map 에 반영."""
    from tools.causal_graph import load_evidence_content
    link_map = {"ev1": ["00_market_review"], "ev3": ["00_market_review"]}
    contents, _ = load_evidence_content(_mock_evidence_08n81(), link_map)
    by_id = {c["evidence_id"]: c for c in contents}
    assert by_id["ev1"]["linked_sections"] == ["00_market_review"]
    assert by_id["ev3"]["linked_sections"] == ["00_market_review"]
    assert by_id["ev4"]["linked_sections"] == []  # 매핑 없음


def test_evidence_content_warning_missing_article_id():
    from tools.causal_graph import load_evidence_content
    contents, w = load_evidence_content([
        {"ref": 99, "title": "no id"},  # article_id 누락
    ])
    assert len(contents) == 0
    assert any("missing article_id" in s for s in w)


# ──────────────────────────────────────────────────────────────────
# 2. Claim extraction (rule-based)
# ──────────────────────────────────────────────────────────────────

def test_claim_extraction_schema_fields():
    from tools.causal_graph import (
        load_evidence_content, extract_claims,
    )
    contents, _ = load_evidence_content(_mock_evidence_08n81())
    claims, w = extract_claims(contents, "08N81", "2026-Q1")
    assert claims, "should extract at least one claim"
    c = claims[0]
    expected_keys = {"claim_id", "source_evidence_id", "claim_text",
                     "claim_type", "entities", "macro_factors",
                     "asset_classes", "fund_codes", "direction",
                     "confidence", "extraction_method", "linked_sections"}
    assert expected_keys.issubset(set(c.keys()))
    assert c["extraction_method"] == "rule_based"
    assert 0.5 <= c["confidence"] <= 0.9


def test_claim_extraction_iran_oil():
    """이란/유가 evidence → event:geopolitical + macro:oil_price."""
    from tools.causal_graph import (
        load_evidence_content, extract_claims,
    )
    contents, _ = load_evidence_content(_mock_evidence_08n81())
    claims, _ = extract_claims(contents, "08N81", "2026-Q1")
    iran_claim = next((c for c in claims
                        if c["source_evidence_id"] == "ev1"), None)
    assert iran_claim is not None
    assert "event:geopolitical" in iran_claim["entities"]
    assert "macro:oil_price" in iran_claim["macro_factors"]
    # event + macro 동시 → claim_type == event_to_macro
    assert iran_claim["claim_type"] == "event_to_macro"


def test_claim_extraction_no_topic_warning():
    """rule 매칭 안되는 evidence (ev8) → claim 미생성 + warning."""
    from tools.causal_graph import (
        load_evidence_content, extract_claims,
    )
    contents, _ = load_evidence_content(_mock_evidence_08n81())
    claims, w = extract_claims(contents, "08N81", "2026-Q1")
    ev8_claim = [c for c in claims if c["source_evidence_id"] == "ev8"]
    assert ev8_claim == []
    assert any("ev8" in s for s in w)


# ──────────────────────────────────────────────────────────────────
# 3. Causal edge builder
# ──────────────────────────────────────────────────────────────────

def test_causal_edges_template_activation():
    """이란/유가/인플레/금리/성장주 5개 토픽이 cover → 4개 chain 활성."""
    from tools.causal_graph import (
        load_evidence_content, extract_claims, build_causal_edges,
    )
    contents, _ = load_evidence_content(_mock_evidence_08n81())
    claims, _ = extract_claims(contents, "08N81", "2026-Q1")
    edges = build_causal_edges(claims)
    pairs = {(e["from"], e["to"]) for e in edges}
    assert ("event:geopolitical", "macro:oil_price") in pairs
    assert ("macro:oil_price", "macro:inflation") in pairs
    assert ("macro:inflation", "macro:interest_rate") in pairs
    assert ("macro:interest_rate", "asset:us_growth_stock") in pairs


# ──────────────────────────────────────────────────────────────────
# 4. Path aggregation
# ──────────────────────────────────────────────────────────────────

def test_path_iran_oil_inflation_rates_growth():
    """대표 path 완전 커버 검증 — chain 5/5, supporting evidence ≥ 4."""
    from tools.causal_graph import (
        load_evidence_content, extract_claims, aggregate_paths,
    )
    contents, _ = load_evidence_content(_mock_evidence_08n81())
    claims, _ = extract_claims(contents, "08N81", "2026-Q1")
    paths = aggregate_paths(claims)
    main = next((p for p in paths
                  if p["path_id"] == "geopolitical_oil_inflation_rates_growth"),
                 None)
    assert main is not None
    assert len(main["covered_chain_nodes"]) == 5  # full cover
    assert main["confidence"] == 1.0
    assert len(main["supporting_evidence_ids"]) >= 4
    assert "ev1" in main["supporting_evidence_ids"]


def test_path_wgbi_domestic_bond():
    """WGBI evidence (ev2) → wgbi_domestic_bond_inflow 활성."""
    from tools.causal_graph import (
        load_evidence_content, extract_claims, aggregate_paths,
    )
    contents, _ = load_evidence_content(_mock_evidence_08n81())
    claims, _ = extract_claims(contents, "08N81", "2026-Q1")
    paths = aggregate_paths(claims)
    wgbi = next((p for p in paths
                  if p["path_id"] == "wgbi_domestic_bond_inflow"), None)
    assert wgbi is not None
    assert "event:wgbi" in wgbi["covered_chain_nodes"]
    assert "ev2" in wgbi["supporting_evidence_ids"]


def test_path_linked_sections_propagated():
    """attribution 의 evidence_id 가 path.linked_sections 에 union."""
    from tools.causal_graph import build_causal_layer
    layer = build_causal_layer(
        _mock_evidence_08n81(), _mock_attributions(),
        "08N81", "2026-Q1",
    )
    main = next(p for p in layer["causal_paths"]
                 if p["path_id"] == "geopolitical_oil_inflation_rates_growth")
    # ev1/ev3 가 00_market_review section 에 묶이고, main path 에 ev1/ev3
    # 가 supporting → linked_sections 에 00_market_review 포함
    assert "00_market_review" in main["linked_sections"]


# ──────────────────────────────────────────────────────────────────
# 5. graph_seed_causal nodes/edges non-empty + topology
# ──────────────────────────────────────────────────────────────────

def test_graph_seed_causal_non_empty():
    from tools.causal_graph import build_causal_layer
    layer = build_causal_layer(
        _mock_evidence_08n81(), _mock_attributions(),
        "08N81", "2026-Q1",
    )
    g = layer["graph_seed_causal"]
    assert g["nodes"], "nodes empty"
    assert g["edges"], "edges empty"
    types = {n["type"] for n in g["nodes"]}
    # claim / evidence / fund / event / macro_factor / asset_class / path 동시 존재
    assert {"claim", "evidence", "fund", "event",
             "macro_factor", "asset_class", "path"}.issubset(types)


def test_graph_seed_causal_has_iran_chain():
    """graph_seed_causal 안에 chain edge (event_raises_macro) 존재."""
    from tools.causal_graph import build_causal_layer
    layer = build_causal_layer(
        _mock_evidence_08n81(), _mock_attributions(),
        "08N81", "2026-Q1",
    )
    g = layer["graph_seed_causal"]
    chain_edges = [e for e in g["edges"]
                    if e["type"] == "event_raises_macro"]
    pairs = {(e["from"], e["to"]) for e in chain_edges}
    assert ("event:geopolitical", "macro:oil_price") in pairs


# ──────────────────────────────────────────────────────────────────
# 6. comment_trace 통합 — 기존 graph_seed 와 graph_seed_causal 동시 존재
# ──────────────────────────────────────────────────────────────────

def _write_full_draft(tmp_path: Path, period: str, fund: str,
                       evidence: list[dict]) -> None:
    pdir = tmp_path / "market_research" / "data" / "report_output" / period
    pdir.mkdir(parents=True, exist_ok=True)
    payload = {
        "fund_code": fund, "period": period, "report_type": "fund",
        "status": "draft", "debate_run_id": "RUN_TEST_R7",
        "draft_comment": "■ 시장\n이란 분쟁으로 유가 상승 [ref:1].\n\n■ 전망\n금리 동결 [ref:3].",
        "draft_comment_raw": "■ 시장\n이란 분쟁으로 유가 상승 [ref:1].\n\n■ 전망\n금리 동결 [ref:3].",
        "evidence_annotations": evidence,
        "data_snapshot": {"fund_return": 1.2, "pa_classes": ["국내주식"],
                          "holdings_top3": [], "trades": {}, "bm_count": 5},
        "inputs_used": {},
    }
    (pdir / f"{fund}.draft.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_comment_trace_includes_both_graphs(tmp_path, monkeypatch):
    """comment_trace.build_trace 결과에 graph_seed (provenance) 와
    graph_seed_causal (R7) 동시 존재 + 기존 R4 schema 깨지지 않음."""
    import importlib
    import tools.comment_trace as ct
    importlib.reload(ct)
    monkeypatch.setattr(ct, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ct, "REPORT_OUTPUT_DIR",
                        tmp_path / "market_research" / "data" / "report_output")
    monkeypatch.setattr(ct, "INCIDENTS_DIR", tmp_path / "debug" / "incidents")

    _write_full_draft(tmp_path, "2026-Q1", "08N81", _mock_evidence_08n81())
    trace = ct.build_trace("2026-Q1", "08N81", market_source_mode="auto")

    # 기존 R4 schema (provenance)
    assert "graph_seed" in trace
    assert "section_attribution" in trace
    assert "attribution_method_summary" in trace
    assert trace["graph_seed"]["nodes"], "provenance nodes empty"

    # R7 신규 schema (causal)
    assert "graph_seed_causal" in trace
    assert "causal_claims" in trace
    assert "causal_paths" in trace
    assert "evidence_contents" in trace
    assert trace["graph_seed_causal"]["nodes"], "causal nodes empty"
    # 메인 path 활성
    main = [p for p in trace["causal_paths"]
             if p["path_id"] == "geopolitical_oil_inflation_rates_growth"]
    assert main and main[0]["confidence"] == 1.0


# ──────────────────────────────────────────────────────────────────
# 7. legacy: evidence_annotations 비어있어도 build_causal_layer 안전
# ──────────────────────────────────────────────────────────────────

def test_build_causal_layer_empty_evidence_safe():
    from tools.causal_graph import build_causal_layer
    layer = build_causal_layer([], [], "07G04", "2026-04")
    assert layer["causal_claims"] == []
    assert layer["causal_paths"] == []
    g = layer["graph_seed_causal"]
    # fund 노드만 존재해야 함 (path/claim 없음)
    assert any(n["type"] == "fund" for n in g["nodes"])
    assert all(n["type"] != "claim" for n in g["nodes"])
