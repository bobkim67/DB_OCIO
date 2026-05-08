# -*- coding: utf-8 -*-
"""R9-A.5 — validate_claim_citations: section-level [claim:hash10] surface.

LLM 호출 0. canonical store / report_output 미접근 (in-memory canonical_claims
fixture 만 사용).
"""
from __future__ import annotations

from market_research.report.evidence_trace import (
    validate_claim_citations, validate_citations, strip_refs,
    strip_claim_refs,
)


def _claim(suffix, period="2026-04", text="canonical claim text"):
    return {
        "claim_id": f"claim:{period}:{suffix}",
        "claim_text": text,
        "period": period,
        "supporting_evidence_ids": ["ev1"],
        "affected_assets": [{"asset_class": "국내주식", "direction": "positive"}],
    }


def test_single_section_claim_explicit_match():
    canonical = [_claim("aaaaaaaaaa"), _claim("bbbbbbbbbb")]
    text = (
        "WTI 가 폭락하였습니다[claim:aaaaaaaaaa]. "
        "JP모건 다이먼이 사모대출 부실을 경고했습니다[claim:bbbbbbbbbb]."
    )
    out = validate_claim_citations(text, canonical)

    cc = out["claim_citations"]
    assert len(cc) == 1  # 단일 section (no ■ header)
    sec = cc[0]
    assert sec["citation_type"] == "claim_explicit"
    assert sec["claim_hashes"] == ["aaaaaaaaaa", "bbbbbbbbbb"]
    assert sec["claim_ids"] == [
        "claim:2026-04:aaaaaaaaaa", "claim:2026-04:bbbbbbbbbb"]
    assert "08_Claims/2026-04_claim_aaaaaaaaaa.md" in sec["wiki_paths"]
    assert "08_Claims/2026-04_claim_bbbbbbbbbb.md" in sec["wiki_paths"]
    assert sec["unmatched_hashes"] == []

    val = out["claim_citation_validation"]
    assert val["total_claim_refs"] == 2
    assert val["matched_count"] == 2
    assert val["unmatched_count"] == 0
    assert val["sections_with_claim_count"] == 1
    assert val["unmatched_hashes"] == []


def test_unmatched_claim_warning():
    canonical = [_claim("aaaaaaaaaa")]
    text = (
        "matched 사실[claim:aaaaaaaaaa]. "
        "unmatched 사실[claim:deadbeef99]."
    )
    out = validate_claim_citations(text, canonical)
    val = out["claim_citation_validation"]
    assert val["matched_count"] == 1
    assert val["unmatched_count"] == 1
    assert val["unmatched_hashes"] == ["deadbeef99"]
    assert any("[claim:deadbeef99]" in w for w in val["warnings"])

    sec = out["claim_citations"][0]
    assert sec["unmatched_hashes"] == ["deadbeef99"]
    assert sec["claim_ids"] == ["claim:2026-04:aaaaaaaaaa"]
    assert sec["wiki_paths"] == ["08_Claims/2026-04_claim_aaaaaaaaaa.md"]


def test_section_without_claim():
    canonical = [_claim("aaaaaaaaaa")]
    text = "단순 사실 문장입니다. 어떤 인용도 없음."
    out = validate_claim_citations(text, canonical)
    sec = out["claim_citations"][0]
    assert sec["citation_type"] == "claim_section_default"
    assert sec["claim_hashes"] == []
    assert sec["claim_ids"] == []
    val = out["claim_citation_validation"]
    assert val["sections_without_claim_count"] == 1
    assert val["sections_with_claim_count"] == 0


def test_multi_section_with_headers():
    canonical = [_claim("aaaaaaaaaa"), _claim("bbbbbbbbbb")]
    text = (
        "■ 1. 시장개요\n"
        "본문 1[claim:aaaaaaaaaa].\n\n"
        "■ 2. 자산군별\n"
        "본문 2[claim:bbbbbbbbbb][claim:aaaaaaaaaa]."
    )
    out = validate_claim_citations(text, canonical)
    cc = out["claim_citations"]
    assert len(cc) == 2
    assert cc[0]["section_title"] == "1. 시장개요"
    assert cc[0]["claim_hashes"] == ["aaaaaaaaaa"]
    assert cc[1]["section_title"] == "2. 자산군별"
    assert sorted(cc[1]["claim_hashes"]) == ["aaaaaaaaaa", "bbbbbbbbbb"]
    val = out["claim_citation_validation"]
    assert val["total_claim_refs"] == 3  # 1 + 2 등장
    assert val["matched_count"] == 3


def test_empty_canonical_marks_all_unmatched():
    text = "사실[claim:aaaaaaaaaa]."
    out = validate_claim_citations(text, [])
    val = out["claim_citation_validation"]
    assert val["matched_count"] == 0
    assert val["unmatched_count"] == 1
    assert val["unmatched_hashes"] == ["aaaaaaaaaa"]


def test_empty_inputs():
    out = validate_claim_citations("", [_claim("aaaaaaaaaa")])
    assert out["claim_citation_validation"]["total_claim_refs"] == 0
    out2 = validate_claim_citations("text without tags", None)
    assert out2["claim_citation_validation"]["total_claim_refs"] == 0


def test_combined_ref_and_claim_validation_independent():
    """validate_citations / validate_claim_citations 동시 호출 — 서로 영향 X."""
    canonical = [_claim("aaaaaaaaaa")]
    annotations = [{"ref": 1, "article_id": "art1", "title": "T1"}]
    text = "병기 문장입니다[ref:1][claim:aaaaaaaaaa]."

    ref_out = validate_citations(text, annotations)
    claim_out = validate_claim_citations(text, canonical)

    rcc = ref_out["comment_citations"][0]
    ccc = claim_out["claim_citations"][0]
    assert rcc["ref_ids"] == [1]
    assert rcc["evidence_ids"] == ["art1"]
    assert ccc["claim_hashes"] == ["aaaaaaaaaa"]
    assert ccc["claim_ids"] == ["claim:2026-04:aaaaaaaaaa"]


def test_compact_claim_wiki_path_preferred():
    """R9-A.5.x — compact schema (R9-A.3.x persistence) 의 wiki_path 가 있으면
    period 재추정 대신 그대로 사용. fund_comment 가 _market_comment_to_inputs
    경유로 받는 claim 에는 'period' 키가 없으므로 회귀 보호."""
    compact_claim = {
        # full canonical 의 'period' 키 의도적 제거 (compact schema)
        "claim_id": "claim:2026-04:aaaaaaaaaa",
        "claim_text": "compact text",
        "wiki_path": "08_Claims/2026-04_claim_aaaaaaaaaa.md",  # preset
    }
    text = "본문[claim:aaaaaaaaaa]."
    out = validate_claim_citations(text, [compact_claim])
    sec = out["claim_citations"][0]
    assert sec["wiki_paths"] == [
        "08_Claims/2026-04_claim_aaaaaaaaaa.md"]
    assert sec["claim_ids"] == ["claim:2026-04:aaaaaaaaaa"]


def test_period_fallback_when_no_wiki_path():
    """compact 에 wiki_path 가 없고 full canonical 처럼 period 만 있으면 기존
    재추정 path 유지 (backward compat)."""
    full_canonical = {
        "claim_id": "claim:2026-04:bbbbbbbbbb",
        "claim_text": "full canonical text",
        "period": "2026-04",
        # 'wiki_path' 키 부재
    }
    text = "본문[claim:bbbbbbbbbb]."
    out = validate_claim_citations(text, [full_canonical])
    sec = out["claim_citations"][0]
    assert sec["wiki_paths"] == [
        "08_Claims/2026-04_claim_bbbbbbbbbb.md"]


def test_explicit_wiki_path_overrides_period():
    """둘 다 있을 때 wiki_path 우선 (preset 신뢰)."""
    claim = {
        "claim_id": "claim:2026-04:cccccccccc",
        "claim_text": "x",
        "period": "2026-04",
        "wiki_path": "08_Claims/custom_path.md",  # 의도적 overrideable
    }
    text = "본문[claim:cccccccccc]."
    out = validate_claim_citations(text, [claim])
    sec = out["claim_citations"][0]
    assert sec["wiki_paths"] == ["08_Claims/custom_path.md"]


def test_strip_helpers_orthogonal():
    """strip_refs / strip_claim_refs 가 서로 다른 태그만 제거 (R9-A.3 회귀)."""
    text = "본문[ref:3][claim:abc1234567]."
    only_ref_removed = strip_refs(text)
    only_claim_removed = strip_claim_refs(text)
    assert only_ref_removed == "본문[claim:abc1234567]."
    assert only_claim_removed == "본문[ref:3]."
