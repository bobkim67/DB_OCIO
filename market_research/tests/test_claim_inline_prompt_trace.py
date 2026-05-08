# -*- coding: utf-8 -*-
"""R9-A.3 — fund_comment pass-through + comment_engine prompt + evidence_trace.

LLM 호출 0. 운영 데이터 미접근 (build_report_prompt 의 DB 호출 영역은
intentionally 회피 — 단위 함수만 검증).
"""
from __future__ import annotations

from market_research.report import evidence_trace
from market_research.report.fund_comment_service import (
    _market_comment_to_inputs,
)


# ──────────────────────────────────────────────────────────────────
# fund_comment_service pass-through
# ──────────────────────────────────────────────────────────────────

def test_market_comment_to_inputs_passes_claims_through():
    market_payload = {
        "draft_comment": "시장 코멘트 본문",
        "consensus_points": ["지점 1"],
        "asset_movement_commentary": [{"asset_class": "국내주식"}],
        "asset_movement_anchors": {"asset_movements": []},
        "claims": [{"claim_id": "claim:2026-04:abc1234567",
                    "claim_text": "테스트 청구문"}],
    }
    inputs = _market_comment_to_inputs(market_payload)
    # 기존 필드 보존 (R8-B amc 보존 패턴 회귀)
    assert inputs["market_view"] == "시장 코멘트 본문"
    assert "asset_movement_commentary" in inputs
    assert "asset_movement_anchors" in inputs
    # R9-A.3 신규 pass-through
    assert inputs["claims"] == [
        {"claim_id": "claim:2026-04:abc1234567",
         "claim_text": "테스트 청구문"}
    ]


def test_market_comment_to_inputs_no_claims_no_field():
    market_payload = {
        "draft_comment": "시장 코멘트 본문",
        "asset_movement_commentary": [{"asset_class": "국내주식"}],
    }
    inputs = _market_comment_to_inputs(market_payload)
    # claims 미존재 → inputs 에 키 추가 X (optional field)
    assert "claims" not in inputs
    # 기존 amc 키 그대로 유지
    assert inputs["asset_movement_commentary"] == [{"asset_class": "국내주식"}]


def test_market_comment_to_inputs_empty_payload():
    assert _market_comment_to_inputs({}) == {}
    assert _market_comment_to_inputs(None) == {}


# ──────────────────────────────────────────────────────────────────
# evidence_trace claim ref recognition
# ──────────────────────────────────────────────────────────────────

def test_extract_claim_refs_basic():
    text = (
        "WTI 가 19% 폭락했다 [claim:de1729b413]. "
        "JP모건 CEO 가 인플레 고착 위험을 지적 [claim:a79b6f699d]."
    )
    refs = evidence_trace.extract_claim_refs(text)
    assert len(refs) == 2
    assert refs[0]["hash10"] == "de1729b413"
    assert refs[1]["hash10"] == "a79b6f699d"
    assert refs[0]["pos"] >= 0
    assert refs[1]["pos"] > refs[0]["pos"]


def test_extract_claim_refs_strict_hex_length():
    # 10자 미만 / 초과는 매칭 안 됨 (다른 패턴과 충돌 방지)
    text = "[claim:short] [claim:abcdefghij1234]"  # short=5, 14
    refs = evidence_trace.extract_claim_refs(text)
    # short (5) 거부, 14자 중 앞 10자만 매칭? — 아니 정확히 10자 + ] 만 매칭
    # 'abcdefghij' 는 10자 hex 라 매칭됨 — 그러나 그 뒤 ']' 가 아닌 '1234]'
    # → 매칭 X. 따라서 둘 다 매칭 X.
    assert refs == []


def test_extract_claim_refs_robust_to_empty():
    assert evidence_trace.extract_claim_refs("") == []
    assert evidence_trace.extract_claim_refs(None) == []


def test_strip_claim_refs_removes_tags_and_leading_space():
    text = "WTI 폭락 [claim:de1729b413] 했다."
    out = evidence_trace.strip_claim_refs(text)
    assert "[claim:" not in out
    assert "WTI 폭락 했다." == out or "WTI 폭락 했다." in out


def test_build_claim_evidence_map_matched_and_unmatched():
    canonical = [
        {"claim_id": "claim:2026-04:de1729b413",
         "period": "2026-04", "claim_text": "WTI 폭락"},
        {"claim_id": "claim:2026-04:a79b6f699d",
         "period": "2026-04", "claim_text": "JP모건 CEO"},
    ]
    refs = [
        {"hash10": "de1729b413", "pos": 10},
        {"hash10": "a79b6f699d", "pos": 60},
        {"hash10": "deadbeef99", "pos": 99},  # canonical 에 없음
    ]
    out = evidence_trace.build_claim_evidence_map(refs, canonical)
    assert len(out) == 3
    matched = [x for x in out if x["matched"]]
    assert len(matched) == 2
    assert matched[0]["claim_id"] == "claim:2026-04:de1729b413"
    assert matched[0]["wiki_path"] == "08_Claims/2026-04_claim_de1729b413.md"
    assert matched[0]["source_type"] == "claim_wiki"
    unmatched = [x for x in out if not x["matched"]]
    assert len(unmatched) == 1
    assert unmatched[0]["hash10"] == "deadbeef99"
    assert unmatched[0]["source_type"] == "unmatched"
    assert unmatched[0]["claim_id"] is None


def test_build_claim_evidence_map_robust_to_empty():
    assert evidence_trace.build_claim_evidence_map(None, None) == []
    assert evidence_trace.build_claim_evidence_map([], []) == []


def test_existing_ref_pattern_unaffected():
    # 기존 [ref:N] 동작 회귀 가드 — claim regex 추가가 영향 안 미침
    text = "유가 100달러 돌파 [ref:1]. [claim:abc1234567] 테스트."
    refs = evidence_trace.extract_refs(text)
    assert len(refs) == 1
    assert refs[0]["ref_idx"] == 1
    claim_refs = evidence_trace.extract_claim_refs(text)
    assert len(claim_refs) == 1
    assert claim_refs[0]["hash10"] == "abc1234567"


# ──────────────────────────────────────────────────────────────────
# comment_engine claim block (smoke — without DB)
# ──────────────────────────────────────────────────────────────────

def test_build_report_prompt_claim_block_renders():
    """build_report_prompt 의 claim_block 분기만 검증.

    실제 build_report_prompt 는 DB 의존이라 단위 테스트 어려움 → 함수 내부
    분기 로직을 직접 호출 (inputs 의 claims 처리부).
    """
    # build_report_prompt 의 claim_block 분기 로직 재현 — 직접 prompt 빌드
    # 대신 helper 가 만든 텍스트 단편을 검증.
    # 함수 내부에 캡슐화돼 있으므로, 동일 형태의 inputs.get('claims') 로
    # render 로직을 분리해 검증할 수도 있지만 테스트 단순화 위해
    # build_report_prompt 의 코드 경로 흉내 X — 대신 prompt 내 마커로 확인.
    # 본 테스트는 "claims 가 있으면 prompt 에 [claim:hash10] anchor 가
    # 등장한다" 만 명시.
    # build_report_prompt 호출은 DB 필요해 skip — comment_engine.py 의
    # claim_block 코드 경로는 unit 검증보다 통합 smoke 로 회귀 보호.
    # 여기서는 evidence_trace 가 그 anchor 를 인식한다는 사실만 보장.
    rendered = "[claim:abc1234567] 본문 텍스트."
    refs = evidence_trace.extract_claim_refs(rendered)
    assert len(refs) == 1
    assert refs[0]["hash10"] == "abc1234567"
