# -*- coding: utf-8 -*-
"""R9-A.5 — comment_trace tool: section 별 claim attribution + summary surface.

LLM 호출 0. 운영 report_output / 08_Claims 미접근 — fund_draft / canonical
은 모두 in-memory fixture.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools import comment_trace as ct
from market_research.analyze import claim_store


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _claim(suffix, period="2026-04", text="canonical claim text",
           assets=None, ev=("ev1",)):
    # default assets≥3 → R9-A.2 Rule A3 통과해 promoted 로 분류됨.
    aas = [{"asset_class": ac, "direction": "positive"}
           for ac in (assets or ["국내주식", "해외주식", "국내채권"])]
    return {
        "schema_version": "1.0.0",
        "claim_id": f"claim:{period}:{suffix}",
        "period": period,
        "source_evidence_ids": list(ev),
        "supporting_evidence_ids": list(ev),
        "counter_evidence_ids": [],
        "claim_text": text,
        "claim_type": "macro_to_asset",
        "affected_assets": aas,
        "causal_chain": [],
        "direction": "positive",
        "horizon": "short",
        "confidence": 0.9,
        "salience": 0.9,
        "linked_wiki_pages": [],
        "extractor_version": "r9a.1-haiku",
        "extraction_method": "llm",
        "warnings": [],
    }


@pytest.fixture
def tmp_canonical(tmp_path, monkeypatch):
    """Redirect claim_store CLAIMS_DATA_DIR to tmp."""
    data_dir = tmp_path / "data_claims"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(claim_store, "CLAIMS_DATA_DIR", data_dir)
    monkeypatch.setattr(claim_store, "PROMOTION_LEDGER_PATH",
                        data_dir / "_promotion_quality.jsonl")
    return data_dir


# ──────────────────────────────────────────────────────────────────
# attribute_section claim attribution
# ──────────────────────────────────────────────────────────────────

def test_attribute_section_claim_matched():
    by_hash = {
        "aaaaaaaaaa": _claim("aaaaaaaaaa", text="WTI 폭락"),
        "bbbbbbbbbb": _claim("bbbbbbbbbb", text="다이먼 사모대출 경고"),
    }
    section = {
        "section_id": "00_main",
        "section_title": "본문",
        "char_range": [0, 200],
        "text": ("WTI 가 폭락하였습니다[claim:aaaaaaaaaa][ref:1]. "
                 "다이먼이 사모대출 부실을 경고[claim:bbbbbbbbbb]."),
    }
    out = ct.attribute_section(
        section,
        evidence_annotations=[{"ref": 1, "article_id": "art1"}],
        market_source_data=None,
        fund_draft={"data_snapshot": {}},
        canonical_claims_by_hash=by_hash,
    )
    assert out["claim_refs"] == ["aaaaaaaaaa", "bbbbbbbbbb"]
    cas = out["claim_attributions"]
    assert len(cas) == 2
    a, b = sorted(cas, key=lambda x: x["hash10"])
    assert a["matched"] is True
    assert a["claim_id"] == "claim:2026-04:aaaaaaaaaa"
    assert a["wiki_path"] == "08_Claims/2026-04_claim_aaaaaaaaaa.md"
    assert a["claim_text_short"] == "WTI 폭락"
    assert b["matched"] is True
    # ref 도 함께 추출
    assert out["ref_ids"] == [1]


def test_attribute_section_claim_unmatched_warning():
    by_hash = {"aaaaaaaaaa": _claim("aaaaaaaaaa")}
    section = {
        "section_id": "00_main",
        "section_title": "본문",
        "char_range": [0, 80],
        "text": "matched[claim:aaaaaaaaaa]. unmatched[claim:deadbeef99].",
    }
    out = ct.attribute_section(
        section, [], None, {"data_snapshot": {}},
        canonical_claims_by_hash=by_hash,
    )
    assert out["claim_unmatched"] == ["deadbeef99"]
    assert any("[claim:deadbeef99]" in w for w in out["warnings"])
    cas = {c["hash10"]: c for c in out["claim_attributions"]}
    assert cas["aaaaaaaaaa"]["matched"] is True
    assert cas["deadbeef99"]["matched"] is False
    assert cas["deadbeef99"]["wiki_path"] is None


def test_attribute_section_no_canonical_dict_keeps_empty():
    """canonical_claims_by_hash=None 시 R9-A.5 surface 0 (회귀 보호)."""
    section = {
        "section_id": "00_main", "section_title": "x",
        "char_range": [0, 50], "text": "본문[claim:aaaaaaaaaa].",
    }
    out = ct.attribute_section(
        section, [], None, {"data_snapshot": {}},
        canonical_claims_by_hash=None,
    )
    assert out["claim_refs"] == []  # 추출 자체 X
    assert out["claim_attributions"] == []
    assert out["claim_unmatched"] == []


def test_attribute_section_long_text_truncates_short():
    long_text = "가" * 200
    by_hash = {"aaaaaaaaaa": _claim("aaaaaaaaaa", text=long_text)}
    section = {
        "section_id": "00_main", "section_title": "x",
        "char_range": [0, 50], "text": "본문[claim:aaaaaaaaaa].",
    }
    out = ct.attribute_section(
        section, [], None, {"data_snapshot": {}},
        canonical_claims_by_hash=by_hash,
    )
    short = out["claim_attributions"][0]["claim_text_short"]
    assert short.endswith("…")
    assert len(short) <= 80


# ──────────────────────────────────────────────────────────────────
# build_trace top-level claim_citation_summary
# ──────────────────────────────────────────────────────────────────

def test_build_trace_top_level_claim_citation_summary(tmp_canonical, monkeypatch, tmp_path):
    """fund_draft + canonical store fixture 로 build_trace 까지 흘려본다."""
    # canonical store seed
    c1 = _claim("aaaaaaaaaa", text="WTI 폭락 91.64달러")
    c2 = _claim("bbbbbbbbbb", text="다이먼 사모대출 경고")
    claim_store.save_claims_canonical(
        period="2026-04", claims=[c1, c2],
        source="test", extractor_version="r9a.1-haiku")

    # fund draft fixture (drop into a temp report_output)
    rep_dir = tmp_path / "report_output" / "2026-04"
    rep_dir.mkdir(parents=True)
    fund_draft = {
        "fund_code": "TEST01",
        "period": "2026-04",
        "draft_comment": (
            "WTI 가 폭락하였습니다[ref:1][claim:aaaaaaaaaa]. "
            "다이먼이 경고했습니다[claim:bbbbbbbbbb]. "
            "추가 사실 문장."
        ),
        "evidence_annotations": [
            {"ref": 1, "article_id": "art1", "title": "WTI 보도",
             "source": "Reuters", "date": "2026-04-08"},
        ],
        "data_snapshot": {"fund_return": 1.23, "pa_by_class": {"국내주식": 0.5},
                          "holdings_top3": [{"name": "x"}]},
    }
    (rep_dir / "TEST01.draft.json").write_text(
        json.dumps(fund_draft, ensure_ascii=False), encoding="utf-8")

    # comment_trace 가 사용하는 REPORT_OUTPUT_DIR 를 tmp 로 고정
    # comment_trace 의 load_fund_draft 가 PROJECT_ROOT 기준 relative_to 를
    # 호출해서 tmp_path 가 PROJECT_ROOT 밖이면 ValueError. fixture 로 직접
    # load 결과를 inject 해 우회.
    fund_draft_local = json.loads(
        (tmp_path / "report_output" / fund_draft["period"]
         / f"{fund_draft['fund_code']}.draft.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        ct, "load_fund_draft",
        lambda p, f: (
            fund_draft_local,
            {"path": "fixture", "exists": True, "mtime": None,
             "schema_detected": "fund.draft"},
        ),
    )
    # market_source / causal_layer / 기타 부수 호출 무력화
    monkeypatch.setattr(
        ct, "find_market_source",
        lambda period, fund_draft, mode="auto", explicit_path=None: (
            None, {"kind": "none", "path": None, "mtime": None}),
    )

    trace = ct.build_trace("2026-04", "TEST01", market_source_mode="none")

    # top-level claim_citation_summary
    assert "claim_citation_summary" in trace
    summ = trace["claim_citation_summary"]
    assert summ["canonical_pool_size"] == 2
    assert summ["matched_count"] == 2  # aaa + bbb 등장
    assert summ["unmatched_count"] == 0
    assert sorted(summ["unique_matched_claims"]) == [
        "aaaaaaaaaa", "bbbbbbbbbb"]
    assert summ["unique_unmatched_hashes"] == []
    assert summ["sections_with_claim_count"] >= 1
    assert summ["load_warning"] is None

    # section_attribution 에 claim_refs 포함
    secs = trace["section_attribution"]
    assert any(s.get("claim_refs") for s in secs)


def test_build_trace_handles_missing_canonical_store(tmp_canonical, monkeypatch, tmp_path):
    """canonical store 부재 (다른 period) → load_warning 없음 + 모두 unmatched
    (matched_count=0, claim_refs 가 있어도 매칭 X)."""
    rep_dir = tmp_path / "report_output" / "2099-01"
    rep_dir.mkdir(parents=True)
    fund_draft = {
        "fund_code": "TEST02",
        "period": "2099-01",
        "draft_comment": "본문[claim:aaaaaaaaaa].",
        "evidence_annotations": [],
        "data_snapshot": {},
    }
    (rep_dir / "TEST02.draft.json").write_text(
        json.dumps(fund_draft), encoding="utf-8")
    # comment_trace 의 load_fund_draft 가 PROJECT_ROOT 기준 relative_to 를
    # 호출해서 tmp_path 가 PROJECT_ROOT 밖이면 ValueError. fixture 로 직접
    # load 결과를 inject 해 우회.
    fund_draft_local = json.loads(
        (tmp_path / "report_output" / fund_draft["period"]
         / f"{fund_draft['fund_code']}.draft.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        ct, "load_fund_draft",
        lambda p, f: (
            fund_draft_local,
            {"path": "fixture", "exists": True, "mtime": None,
             "schema_detected": "fund.draft"},
        ),
    )
    # market_source / causal_layer / 기타 부수 호출 무력화
    monkeypatch.setattr(
        ct, "find_market_source",
        lambda period, fund_draft, mode="auto", explicit_path=None: (
            None, {"kind": "none", "path": None, "mtime": None}),
    )

    trace = ct.build_trace("2099-01", "TEST02", market_source_mode="none")
    summ = trace["claim_citation_summary"]
    assert summ["canonical_pool_size"] == 0
    assert summ["matched_count"] == 0
    # claim_refs 자체는 없음 (by_hash 가 비어있어 attribute_section 이 None
    # 처럼 동작 — by_hash={} 라 모든 claim 이 unmatched 로 surface).
    assert summ["unmatched_count"] == 1
    assert summ["unique_unmatched_hashes"] == ["aaaaaaaaaa"]


def test_build_trace_supports_quarterly_period(tmp_canonical, monkeypatch, tmp_path):
    """period=2026-Q1 시 1/2/3월 claim store 모두 union 으로 매칭."""
    claim_store.save_claims_canonical(
        period="2026-02", claims=[_claim("fab1111111", period="2026-02")],
        source="test", extractor_version="r9a.1-haiku")
    claim_store.save_claims_canonical(
        period="2026-03", claims=[_claim("aabbccddee", period="2026-03")],
        source="test", extractor_version="r9a.1-haiku")

    rep_dir = tmp_path / "report_output" / "2026-Q1"
    rep_dir.mkdir(parents=True)
    fund_draft = {
        "fund_code": "TEST03",
        "period": "2026-Q1",
        "draft_comment": "본문[claim:fab1111111][claim:aabbccddee].",
        "evidence_annotations": [],
        "data_snapshot": {},
    }
    (rep_dir / "TEST03.draft.json").write_text(
        json.dumps(fund_draft), encoding="utf-8")
    # comment_trace 의 load_fund_draft 가 PROJECT_ROOT 기준 relative_to 를
    # 호출해서 tmp_path 가 PROJECT_ROOT 밖이면 ValueError. fixture 로 직접
    # load 결과를 inject 해 우회.
    fund_draft_local = json.loads(
        (tmp_path / "report_output" / fund_draft["period"]
         / f"{fund_draft['fund_code']}.draft.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        ct, "load_fund_draft",
        lambda p, f: (
            fund_draft_local,
            {"path": "fixture", "exists": True, "mtime": None,
             "schema_detected": "fund.draft"},
        ),
    )
    # market_source / causal_layer / 기타 부수 호출 무력화
    monkeypatch.setattr(
        ct, "find_market_source",
        lambda period, fund_draft, mode="auto", explicit_path=None: (
            None, {"kind": "none", "path": None, "mtime": None}),
    )

    trace = ct.build_trace("2026-Q1", "TEST03", market_source_mode="none")
    summ = trace["claim_citation_summary"]
    assert summ["canonical_pool_size"] == 2  # feb + mar union
    assert summ["matched_count"] == 2
    assert summ["unmatched_count"] == 0
