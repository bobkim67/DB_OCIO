# -*- coding: utf-8 -*-
"""R9-A.5 — fund_comment_service 가 claim_citations 를 draft 에 persist 하는지.

LLM 호출 0. fund_comment_service.generate_fund_comment_and_save 는 DB
의존이라 단위 호출 어려움 → claim 인용 path 만 격리해 검증 (validate_claim_citations
가 호출돼서 claim_citations / claim_citation_validation 키가 생성된 draft
shape 이 되는지).

본 테스트는 inputs['claims'] pass-through + validate_claim_citations 결과가
draft 에 들어가는 경로를 단위 검증한다. 실 DB / LLM 호출 없음.
"""
from __future__ import annotations

from market_research.report.evidence_trace import validate_claim_citations


def _claim(suffix, period="2026-04", text="canonical claim text"):
    return {
        "claim_id": f"claim:{period}:{suffix}",
        "period": period,
        "claim_text": text,
        "supporting_evidence_ids": ["ev1"],
        "affected_assets": [{"asset_class": "국내주식", "direction": "positive"}],
    }


def test_claim_citations_shape_in_fund_draft_simulation():
    """fund_comment_service 의 claim 분기 로직을 시뮬레이션 — validate_claim_citations
    출력이 그대로 draft.claim_citations / draft.claim_citation_validation 으로
    들어갈 수 있는 shape 인지."""
    fund_canonical_claims = [
        _claim("aaaaaaaaaa"), _claim("bbbbbbbbbb"),
    ]
    comment_text_raw = (
        "WTI 가 폭락했습니다[ref:1][claim:aaaaaaaaaa]. "
        "다이먼이 사모대출 부실을 경고[claim:bbbbbbbbbb]."
    )
    result = validate_claim_citations(comment_text_raw, fund_canonical_claims)
    claim_citations = result["claim_citations"]
    claim_citation_validation = result["claim_citation_validation"]

    # draft 에 들어갈 shape
    draft_data = {
        "fund_code": "TEST01",
        "claim_citations": claim_citations,
        "claim_citation_validation": claim_citation_validation,
    }
    # claim_citations: list[dict]
    assert isinstance(draft_data["claim_citations"], list)
    sec0 = draft_data["claim_citations"][0]
    assert sec0["citation_type"] == "claim_explicit"
    assert sec0["claim_hashes"] == ["aaaaaaaaaa", "bbbbbbbbbb"]
    assert sec0["claim_ids"] == [
        "claim:2026-04:aaaaaaaaaa", "claim:2026-04:bbbbbbbbbb"]
    # validation
    val = draft_data["claim_citation_validation"]
    assert val["matched_count"] == 2
    assert val["unmatched_count"] == 0
    assert val["sections_with_claim_count"] == 1


def test_no_claims_input_keeps_empty_persistence():
    """inputs.claims 가 빈 list 면 claim_citations 에 section_default 만 채워짐
    (matched=0, unmatched=0). 회귀 — 기존 fund draft 가 claim_* 키 추가만 받는다."""
    result = validate_claim_citations("단순 사실 문장입니다.", [])
    assert result["claim_citations"][0]["citation_type"] == "claim_section_default"
    assert result["claim_citation_validation"]["total_claim_refs"] == 0
    assert result["claim_citation_validation"]["matched_count"] == 0


def test_unmatched_claim_in_fund_comment():
    """LLM 이 promoted 아닌 hash10 을 만들면 unmatched_hashes 로 surface."""
    fund_canonical_claims = [_claim("aaaaaaaaaa")]
    comment_text_raw = "본문[claim:aaaaaaaaaa][claim:deadbeef99]."
    result = validate_claim_citations(comment_text_raw, fund_canonical_claims)
    val = result["claim_citation_validation"]
    assert val["matched_count"] == 1
    assert val["unmatched_count"] == 1
    assert val["unmatched_hashes"] == ["deadbeef99"]
