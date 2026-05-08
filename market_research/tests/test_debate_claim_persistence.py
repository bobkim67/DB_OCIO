# -*- coding: utf-8 -*-
"""R9-A.3.x (D-X-A) — debate → draft → final → fund_comment claim wiring.

LLM 호출 0. 운영 산출물 미접근. monkeypatch 로 _call_llm + _build_shared_context
의존성 차단, save_draft / approve_and_save_final 은 tmp report_output 사용.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_research.report import debate_engine, debate_service, report_store
from market_research.report.fund_comment_service import (
    _market_comment_to_inputs,
)


def _claim(suffix, period="2026-04", text="canonical claim sample text"):
    return {
        "schema_version": "1.0.0",
        "claim_id": f"claim:{period}:{suffix}",
        "period": period,
        "claim_text": text,
        "claim_type": "macro_to_asset",
        "affected_assets": [
            {"asset_class": "국내주식", "direction": "positive"},
            {"asset_class": "해외주식", "direction": "positive"},
            {"asset_class": "국내채권", "direction": "negative"},
        ],
        "causal_chain": [
            {"source": "x", "target": "y", "relation": "raises"},
            {"source": "y", "target": "z", "relation": "raises"},
        ],
        "direction": "positive",
        "horizon": "short",
        "confidence": 0.91,
        "salience": 0.88,
        "source_evidence_ids": ["ev1", "ev2"],
        "supporting_evidence_ids": ["ev1", "ev2"],
        "counter_evidence_ids": [],
        "linked_wiki_pages": [],
        "extractor_version": "r9a.1-haiku",
        "extraction_method": "llm",
        "warnings": [],
    }


# ──────────────────────────────────────────────────────────────────
# _compact_claims_for_persistence
# ──────────────────────────────────────────────────────────────────

def test_compact_claims_8_fields_only():
    c = _claim("aaaaaaaaaa")
    out = debate_engine._compact_claims_for_persistence([c])
    assert len(out) == 1
    persisted = out[0]
    assert set(persisted.keys()) == {
        "claim_id", "claim_text", "claim_type", "affected_assets",
        "confidence", "salience", "supporting_evidence_ids",
        "wiki_filename", "wiki_path",
    }
    assert persisted["claim_id"] == "claim:2026-04:aaaaaaaaaa"
    assert persisted["wiki_filename"] == "2026-04_claim_aaaaaaaaaa.md"
    assert persisted["wiki_path"] == "08_Claims/2026-04_claim_aaaaaaaaaa.md"
    assert persisted["confidence"] == 0.91
    assert persisted["salience"] == 0.88
    # heavier fields not persisted (causal_chain / counter_evidence_ids
    # / linked_wiki_pages / period 등 R9-A.5 trace 필요분만 보존)
    assert "causal_chain" not in persisted
    assert "counter_evidence_ids" not in persisted


def test_compact_claims_robust_to_empty():
    assert debate_engine._compact_claims_for_persistence(None) == []
    assert debate_engine._compact_claims_for_persistence([]) == []
    assert debate_engine._compact_claims_for_persistence([{}, "bad"]) == [{
        "claim_id": "", "claim_text": "", "claim_type": "",
        "affected_assets": [], "confidence": None, "salience": None,
        "supporting_evidence_ids": [], "wiki_filename": None,
        "wiki_path": None,
    }]


# ──────────────────────────────────────────────────────────────────
# debate_service.run_debate_and_save preserves claims to draft
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_report_output(tmp_path, monkeypatch):
    out = tmp_path / "report_output"
    out.mkdir(parents=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", out)
    return out


def test_run_debate_and_save_preserves_claims(monkeypatch, tmp_report_output):
    """run_market_debate 가 result['claims'] 를 반환하면 draft 에 보존되는지."""
    fake_result = {
        "year": 2026, "month": 4,
        "debate_run_id": "fake_run_id",
        "debated_at": "2026-05-08T11:00:00",
        "agents": {"bull": {"stance": "bullish", "key_points": []}},
        "synthesis": {"customer_comment": "텍스트.",
                       "consensus_points": ["c1"], "disagreements": [],
                       "tail_risks": [], "admin_summary": "x"},
        "debate_narrative": {"debate_narrative": "n",
                              "canonical_snapshot": {},
                              "diverges_from_canonical": False},
        "_evidence_ids": [],
        "asset_movement_anchors": {"asset_movements": []},
        "asset_movement_commentary": [],
        "asset_movement_commentary_fallback": [],
        "asset_movement_commentary_warnings_by_agent": {},
        "claims": debate_engine._compact_claims_for_persistence(
            [_claim("aaaaaaaaaa"), _claim("bbbbbbbbbb")]),
    }
    monkeypatch.setattr(
        "market_research.report.debate_engine.run_market_debate",
        lambda y, m, **kw: fake_result,
    )
    # debate_memory write 차단 (file write 외부 영향 0)
    monkeypatch.setattr(
        "market_research.wiki.debate_memory.write_debate_memory_page",
        lambda draft, regime_file: Path("/tmp/dummy.md"),
    )

    draft = debate_service.run_debate_and_save(
        mode="월별", year=2026, period_num=4,
        fund_code="_market", period_key="2026-04",
    )
    assert "claims" in draft
    assert len(draft["claims"]) == 2
    assert draft["claims"][0]["claim_id"] == "claim:2026-04:aaaaaaaaaa"

    # disk 에서 draft 읽어도 claims 보존되는지
    loaded = report_store.load_draft("2026-04", "_market")
    assert loaded is not None
    assert "claims" in loaded
    assert len(loaded["claims"]) == 2
    assert all(set(c.keys()) == {
        "claim_id", "claim_text", "claim_type", "affected_assets",
        "confidence", "salience", "supporting_evidence_ids",
        "wiki_filename", "wiki_path",
    } for c in loaded["claims"])


def test_run_debate_and_save_no_claims_key_when_result_missing(monkeypatch, tmp_report_output):
    """result 에 claims 키가 없으면 draft 에도 미생성 (backward-compat 회귀)."""
    fake_result = {
        "year": 2026, "month": 4, "debate_run_id": "x",
        "debated_at": "2026-05-08T11:00:00",
        "agents": {}, "synthesis": {"customer_comment": "x.",
                                       "consensus_points": [],
                                       "disagreements": [],
                                       "tail_risks": [],
                                       "admin_summary": ""},
        "debate_narrative": {"debate_narrative": "",
                              "canonical_snapshot": {},
                              "diverges_from_canonical": False},
        "_evidence_ids": [],
        # 'claims' 키 없음
    }
    monkeypatch.setattr(
        "market_research.report.debate_engine.run_market_debate",
        lambda y, m, **kw: fake_result,
    )
    monkeypatch.setattr(
        "market_research.wiki.debate_memory.write_debate_memory_page",
        lambda draft, regime_file: Path("/tmp/dummy.md"),
    )

    draft = debate_service.run_debate_and_save(
        mode="월별", year=2026, period_num=4,
        fund_code="_market", period_key="2026-04",
    )
    assert "claims" not in draft  # for-loop 가 result 에 없으면 skip


# ──────────────────────────────────────────────────────────────────
# approve_and_save_final preserves claims
# ──────────────────────────────────────────────────────────────────

def test_approve_and_save_final_preserves_claims(tmp_report_output):
    """draft 에 claims 가 있으면 final 에도 보존되는지."""
    period = "2026-04"
    fund_code = "_market"
    draft_data = {
        "fund_code": fund_code, "period": period, "status": "draft_generated",
        "draft_comment": "고객용 코멘트 본문.",
        "consensus_points": [], "tail_risks": [],
        "debate_run_id": "abc", "generated_at": "x", "model": "claude-opus-4-6",
        "cost_usd": 0.34,
        "claims": debate_engine._compact_claims_for_persistence(
            [_claim("aaaaaaaaaa")]),
    }
    report_store.save_draft(period, fund_code, draft_data)

    report_store.approve_and_save_final(period, fund_code, approved_by="test")
    final = report_store.load_final(period, fund_code)
    assert final is not None
    assert "claims" in final
    assert len(final["claims"]) == 1
    assert final["claims"][0]["claim_id"] == "claim:2026-04:aaaaaaaaaa"
    # 기존 final 키 회귀 0
    assert final["status"] == "approved"
    assert final["approved"] is True
    assert final["final_comment"] == "고객용 코멘트 본문."


def test_approve_and_save_final_empty_claims_when_draft_missing(tmp_report_output):
    """draft 에 claims 가 없으면 final.claims = [] (backward-compat)."""
    period = "2026-04"
    fund_code = "_market"
    draft_data = {
        "fund_code": fund_code, "period": period, "status": "draft_generated",
        "draft_comment": "x.",
        "consensus_points": [], "tail_risks": [],
        "debate_run_id": "x", "generated_at": "x", "model": "x",
        "cost_usd": 0,
        # 'claims' 키 없음
    }
    report_store.save_draft(period, fund_code, draft_data)
    report_store.approve_and_save_final(period, fund_code)
    final = report_store.load_final(period, fund_code)
    assert final["claims"] == []  # default empty


# ──────────────────────────────────────────────────────────────────
# _market_comment_to_inputs end-to-end pass-through
# ──────────────────────────────────────────────────────────────────

def test_market_comment_to_inputs_passes_compact_claims():
    """compact claims 가 inputs['claims'] 로 전달."""
    compact_claims = debate_engine._compact_claims_for_persistence(
        [_claim("aaaaaaaaaa"), _claim("bbbbbbbbbb")])
    market_payload = {
        "draft_comment": "본문",
        "consensus_points": [],
        "claims": compact_claims,
    }
    inputs = _market_comment_to_inputs(market_payload)
    assert "claims" in inputs
    assert len(inputs["claims"]) == 2
    assert inputs["claims"][0]["claim_id"] == "claim:2026-04:aaaaaaaaaa"
    # 8필드 schema 보존
    assert inputs["claims"][0]["wiki_path"] == "08_Claims/2026-04_claim_aaaaaaaaaa.md"


def test_final_load_with_claims_passes_to_inputs():
    """fund_comment 가 final 우선 로드 → claims 가 비어있지 않은 채 inputs 도달."""
    final_payload = {
        "fund_code": "_market",
        "period": "2026-04",
        "status": "approved",
        "final_comment": "최종 코멘트",
        "claims": debate_engine._compact_claims_for_persistence(
            [_claim("aaaaaaaaaa")]),
    }
    inputs = _market_comment_to_inputs(final_payload)
    assert inputs["market_view"] == "최종 코멘트"
    assert "claims" in inputs
    assert len(inputs["claims"]) == 1


# ──────────────────────────────────────────────────────────────────
# build_report_prompt claim_block 생성
# ──────────────────────────────────────────────────────────────────

def test_build_report_prompt_renders_claim_block_when_claims_present():
    """inputs['claims'] 가 있으면 build_report_prompt 가 claim_block 을 prompt 에
    inline. 단위 검증 — DB / data_ctx 의 다른 path 는 minimal 로 채움."""
    from market_research.report.comment_engine import build_report_prompt

    inputs = {
        "claims": debate_engine._compact_claims_for_persistence(
            [_claim("aaaaaaaaaa", text="WTI 폭락 이벤트 reasoning")]),
    }
    data_ctx = {
        "bm": {}, "fund_ret": None, "pa": {},
        "holdings_end": {}, "holdings_diff": [],
    }
    # build_report_prompt 시그니처 (fund_code, year, quarter, data_ctx, inputs, ...)
    prompt = build_report_prompt(
        fund_code="08K88", year=2026, quarter=2,
        data_ctx=data_ctx, inputs=inputs,
    )
    # claim block 핵심 마커
    assert "## 참고 가능한 확정 Claim (R9-A.3, 보조 자료)" in prompt
    assert "[claim:aaaaaaaaaa]" in prompt
    assert "WTI 폭락" in prompt
    # caveat 인용 규칙
    assert "claim 은 근거 보조 자료입니다" in prompt
    assert "[claim:hash10]" in prompt


def test_build_report_prompt_skips_claim_block_when_no_claims():
    from market_research.report.comment_engine import build_report_prompt

    inputs = {}  # no claims
    data_ctx = {
        "bm": {}, "fund_ret": None, "pa": {},
        "holdings_end": {}, "holdings_diff": [],
    }
    prompt = build_report_prompt(
        fund_code="08K88", year=2026, quarter=2,
        data_ctx=data_ctx, inputs=inputs,
    )
    assert "## 참고 가능한 확정 Claim (R9-A.3, 보조 자료)" not in prompt


# ──────────────────────────────────────────────────────────────────
# Final 보존 — evidence_annotations 부재해도 claims 유지
# ──────────────────────────────────────────────────────────────────

def test_final_preserves_claims_without_evidence_annotations(tmp_report_output):
    """final 은 evidence_annotations 를 보존하지 않지만 claims 는 유지 (D-X-A 결정)."""
    period = "2026-04"
    fund_code = "_market"
    draft_data = {
        "fund_code": fund_code, "period": period, "status": "draft_generated",
        "draft_comment": "본문",
        "evidence_annotations": [{"ref": 1, "article_id": "art1"}],
        "consensus_points": [], "tail_risks": [],
        "debate_run_id": "x", "generated_at": "x", "model": "x",
        "cost_usd": 0,
        "claims": debate_engine._compact_claims_for_persistence(
            [_claim("aaaaaaaaaa")]),
    }
    report_store.save_draft(period, fund_code, draft_data)
    report_store.approve_and_save_final(period, fund_code)
    final = report_store.load_final(period, fund_code)
    # evidence_annotations 는 final 에 미보존 (기존 정책 유지)
    assert "evidence_annotations" not in final
    # claims 는 유지
    assert "claims" in final
    assert len(final["claims"]) == 1
