"""R4 회귀: comment_trace tool + gateway.

LLM 호출 0. 운영 데이터 / report_output 변경 0.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────
# 1. tool helper 단독 테스트
# ──────────────────────────────────────────────────────────────────

def test_split_sections_with_headers():
    from tools.comment_trace import split_sections
    txt = "■ 첫번째 섹션\n\n본문 1\n\n■ 두번째 섹션\n\n본문 2\n\n■ 세번째 섹션\n\n본문 3"
    sections = split_sections(txt)
    assert len(sections) == 3
    titles = [s["section_title"] for s in sections]
    assert titles == ["첫번째 섹션", "두번째 섹션", "세번째 섹션"]
    # char_range 일관성
    for s in sections:
        a, b = s["char_range"]
        assert 0 <= a < b <= len(txt)


def test_split_sections_no_header():
    """■ 없으면 single 'main' section."""
    from tools.comment_trace import split_sections
    sections = split_sections("plain comment without headers")
    assert len(sections) == 1
    assert sections[0]["section_id"] == "00_main"


def test_split_sections_empty():
    from tools.comment_trace import split_sections
    sections = split_sections("")
    assert len(sections) == 1
    assert sections[0]["char_range"] == [0, 0]


def test_attribute_section_explicit_ref():
    """[ref:N] 있으면 explicit_ref 방식."""
    from tools.comment_trace import attribute_section
    section = {
        "section_id": "00_test",
        "section_title": "Test",
        "char_range": [0, 100],
        "text": "국내주식 +5% 해외주식 -2% 라고 [ref:1] 그리고 [ref:3] 참조."
    }
    annotations = [
        {"ref": 1, "article_id": "abc111", "title": "T1"},
        {"ref": 2, "article_id": "abc222", "title": "T2"},
        {"ref": 3, "article_id": "abc333", "title": "T3"},
    ]
    fund_draft = {"data_snapshot": {"fund_return": -2.7,
                                       "pa_classes": ["국내주식"],
                                       "holdings_top3": [("FX", 50)],
                                       "trades": {}, "bm_count": 33}}
    a = attribute_section(section, annotations, None, fund_draft)
    assert a["attribution_method"] == "explicit_ref"
    assert a["ref_ids"] == [1, 3]
    assert "abc111" in a["evidence_ids"]
    assert "abc333" in a["evidence_ids"]
    assert "abc222" not in a["evidence_ids"]
    assert "국내주식" in a["asset_classes_mentioned"]
    assert "해외주식" in a["asset_classes_mentioned"]
    assert "fund_return" in a["fund_data_keys"]
    assert "pa_by_class" in a["fund_data_keys"]


def test_attribute_section_no_ref_section_default():
    """[ref:N] 없으면 section_default + warning."""
    from tools.comment_trace import attribute_section
    section = {
        "section_id": "00_test", "section_title": "T",
        "char_range": [0, 50], "text": "국내주식 강세, FX 안정.",
    }
    annotations = [
        {"ref": 1, "article_id": "x111", "title": "X1"},
        {"ref": 2, "article_id": "x222", "title": "X2"},
    ]
    a = attribute_section(section, annotations, None, {"data_snapshot": {}})
    assert a["attribution_method"] == "section_default"
    assert a["ref_ids"] == []
    # section_default 면 모든 evidence 를 section-level 로 attribute
    assert set(a["evidence_ids"]) == {"x111", "x222"}
    assert any("section-level" in w for w in a["warnings"])


def test_attribute_section_ref_unresolved():
    """ref:N 인데 annotations 에 매핑 실패 → warning."""
    from tools.comment_trace import attribute_section
    section = {"section_id": "00_t", "section_title": "T",
                "char_range": [0, 30], "text": "[ref:99] missing"}
    a = attribute_section(section, [], None, {"data_snapshot": {}})
    assert a["attribution_method"] == "explicit_ref"
    assert any("ref:99" in w for w in a["warnings"])


# ──────────────────────────────────────────────────────────────────
# 2. graph_seed
# ──────────────────────────────────────────────────────────────────

def test_graph_seed_node_edge_types_enum():
    from tools.comment_trace import build_graph_seed, NODE_TYPES, EDGE_TYPES
    attrs = [
        {
            "section_id": "00_a", "section_title": "A",
            "char_range": [0, 100],
            "attribution_method": "explicit_ref",
            "ref_ids": [1], "evidence_ids": ["aid1"],
            "wiki_pages": ["01_Events/2026-01_event_x.md"],
            "asset_classes_mentioned": ["국내주식"],
            "fund_data_keys": ["fund_return"],
            "warnings": [],
        }
    ]
    annotations = [{"ref": 1, "article_id": "aid1", "title": "ev1",
                     "date": "2026-01-15", "source": "Reuters"}]
    market_meta = {"kind": "debug_incidents", "path": "x.json",
                    "matched_by": "debate_run_id", "confidence": "high"}
    g = build_graph_seed("08N81", "2026-Q1", attrs, annotations,
                          market_meta, {})
    # 모든 node type 이 enum 안
    for n in g["nodes"]:
        assert n["type"] in NODE_TYPES, f'invalid node type {n["type"]}'
    for e in g["edges"]:
        assert e["type"] in EDGE_TYPES, f'invalid edge type {e["type"]}'

    # 기본 nodes 존재
    types = {n["type"] for n in g["nodes"]}
    assert "comment" in types
    assert "fund" in types
    assert "comment_section" in types
    assert "market_source" in types
    assert "evidence" in types
    assert "wiki_page" in types
    assert "asset_class" in types
    assert "metric" in types

    # edges non-empty
    assert len(g["edges"]) >= 6


def test_graph_seed_warnings_attached_to_section():
    from tools.comment_trace import build_graph_seed
    attrs = [{
        "section_id": "00_w", "section_title": "W",
        "char_range": [0, 10], "attribution_method": "section_default",
        "ref_ids": [], "evidence_ids": [], "wiki_pages": [],
        "asset_classes_mentioned": [], "fund_data_keys": [],
        "warnings": ["w1", "w2"],
    }]
    g = build_graph_seed("F", "2026-04", attrs, [],
                          {"kind": "none"}, {})
    warning_nodes = [n for n in g["nodes"] if n["type"] == "warning"]
    assert len(warning_nodes) == 2
    warning_edges = [e for e in g["edges"] if e["type"] == "warning_applies_to_section"]
    assert len(warning_edges) == 2


# ──────────────────────────────────────────────────────────────────
# 3. market_source matching
# ──────────────────────────────────────────────────────────────────

def test_find_market_source_explicit_path(tmp_path):
    from tools.comment_trace import find_market_source
    fp = tmp_path / "fake_market.json"
    fp.write_text(json.dumps({"debate_run_id": "x"}), encoding="utf-8")
    data, meta = find_market_source(
        "2026-Q1", {"debate_run_id": "x"},
        mode="path", explicit_path=str(fp),
    )
    assert meta["kind"] == "explicit_path"
    assert meta["matched_by"] == "explicit_path"
    assert meta["confidence"] == "high"
    assert meta["exists"] is True
    assert data is not None


def test_find_market_source_path_missing(tmp_path):
    from tools.comment_trace import find_market_source
    data, meta = find_market_source(
        "2026-Q1", {}, mode="path",
        explicit_path=str(tmp_path / "nonexistent.json"),
    )
    assert meta["kind"] == "explicit_path"
    assert meta["confidence"] == "none"
    assert meta["exists"] is False
    assert data is None


def test_find_market_source_auto_fallback_to_none(monkeypatch, tmp_path):
    """auto 모드에서 모든 source 부재 → kind='none'."""
    from tools import comment_trace as ct
    monkeypatch.setattr(ct, "INCIDENTS_DIR", tmp_path / "no_incidents")
    monkeypatch.setattr(ct, "REPORT_OUTPUT_DIR", tmp_path / "no_reports")
    data, meta = ct.find_market_source("2026-Q1", {}, mode="auto")
    assert meta["kind"] == "none"
    assert meta["confidence"] == "none"
    assert data is None


# ──────────────────────────────────────────────────────────────────
# 4. Top-level schema 검증 (실 운영 데이터)
# ──────────────────────────────────────────────────────────────────

REQUIRED_TOP_KEYS = {
    "schema_version", "tool_version", "trace_id", "report_id",
    "fund_code", "period", "generated_at",
    "report_source", "market_source",
    "attribution_level", "attribution_method_summary",
    "sources", "section_attribution", "graph_seed",
    "warnings", "errors",
}


def test_build_trace_top_level_schema():
    """실 운영 fund draft (08N81 2026-Q1) — schema 검증."""
    from tools.comment_trace import build_trace
    t = build_trace("2026-Q1", "08N81", market_source_mode="auto")
    missing = REQUIRED_TOP_KEYS - set(t.keys())
    assert not missing, f"missing keys: {missing}"
    assert t["attribution_level"] == "section"
    assert t["fund_code"] == "08N81"
    assert t["period"] == "2026-Q1"
    assert t["trace_id"] == "comment_trace:08N81@2026-Q1"
    g = t["graph_seed"]
    assert isinstance(g["nodes"], list)
    assert isinstance(g["edges"], list)
    # 최소 nodes/edges (comment + fund + sections)
    assert len(g["nodes"]) >= 4
    assert len(g["edges"]) >= 3


# ──────────────────────────────────────────────────────────────────
# 5. Gateway path traversal + load
# ──────────────────────────────────────────────────────────────────

def test_gateway_invalid_period():
    from api.services import comment_trace_gateway as ctg
    for bad in ("../etc", "1234-99", "2026-13", "2026", "abc-04"):
        try:
            ctg.load_trace(bad, "08N81")
            assert False, f"should reject period {bad!r}"
        except ValueError:
            pass


def test_gateway_invalid_fund():
    from api.services import comment_trace_gateway as ctg
    for bad in ("../passwd", "with space", "abc/def", ""):
        try:
            ctg.load_trace("2026-Q1", bad)
            assert False, f"should reject fund {bad!r}"
        except ValueError:
            pass


def test_gateway_invalid_trace_id():
    from api.services import comment_trace_gateway as ctg
    for bad in ("../etc@2026-Q1", "08N81@..", "08N81@1234-99",
                "no_at_sign", "08N81 @ 2026-Q1"):
        try:
            ctg.load_trace_by_id(bad)
            assert False, f"should reject trace_id {bad!r}"
        except ValueError:
            pass


def test_gateway_load_real_08N81():
    """실 trace load (위 build_trace 가 만든 것)."""
    from api.services import comment_trace_gateway as ctg
    t = ctg.load_trace("2026-Q1", "08N81")
    if t is None:
        return  # not generated yet
    assert t["fund_code"] == "08N81"
    assert t["period"] == "2026-Q1"
    assert "graph_seed" in t


def test_gateway_list_traces():
    from api.services import comment_trace_gateway as ctg
    items = ctg.list_traces()
    assert isinstance(items, list)
    if items:
        first = items[0]
        for k in ("trace_id", "fund_code", "period", "schema_version",
                  "graph_node_count", "graph_edge_count"):
            assert k in first


def test_gateway_parse_trace_id():
    from api.services.comment_trace_gateway import parse_trace_id
    fund, period = parse_trace_id("08N81@2026-Q1")
    assert fund == "08N81"
    assert period == "2026-Q1"


if __name__ == "__main__":
    import unittest.mock as _m

    class FakeMonkey:
        def __init__(self):
            self._patches = []
        def setattr(self, target, name, value):
            p = _m.patch.object(target, name, value)
            p.start()
            self._patches.append(p)
        def stop_all(self):
            for p in self._patches:
                p.stop()

    no_args = [
        test_split_sections_with_headers,
        test_split_sections_no_header,
        test_split_sections_empty,
        test_attribute_section_explicit_ref,
        test_attribute_section_no_ref_section_default,
        test_attribute_section_ref_unresolved,
        test_graph_seed_node_edge_types_enum,
        test_graph_seed_warnings_attached_to_section,
        test_build_trace_top_level_schema,
        test_gateway_invalid_period,
        test_gateway_invalid_fund,
        test_gateway_invalid_trace_id,
        test_gateway_load_real_08N81,
        test_gateway_list_traces,
        test_gateway_parse_trace_id,
    ]
    for fn in no_args:
        fn()
        print(f"PASS {fn.__name__}")

    # tmp_path needed
    with tempfile.TemporaryDirectory(prefix="r4test_") as td:
        tp = Path(td)
        for fn in [test_find_market_source_explicit_path,
                   test_find_market_source_path_missing]:
            fn(tp)
            print(f"PASS {fn.__name__}")
        # monkeypatch needed
        mp = FakeMonkey()
        try:
            test_find_market_source_auto_fallback_to_none(mp, tp)
            print("PASS test_find_market_source_auto_fallback_to_none")
        finally:
            mp.stop_all()
    print("ALL PASS")
