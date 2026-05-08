# -*- coding: utf-8 -*-
"""R9-A.3.x (D-3-A) — claim citation instruction in agent + synthesis prompts.

목표:
  - _build_agent_prompt 가 claims_block 있을 때 _CLAIM_CITATION_INSTRUCTION 부착
  - _synthesize_debate 의 comment_prompt 에도 claims_block + citation rule 주입
  - [ref:N] 와 [claim:hash10] 양쪽 trace 가 동시 작동
  - strip_claim_refs 가 [claim:hash10] 만 제거하고 [ref:N] 보존

LLM 호출 0 — synthesis prompt 검증은 _call_llm 을 monkey-patch 해 prompt 캡처.
"""
from __future__ import annotations

import pytest

from market_research.report import debate_engine, evidence_trace


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _claim(suffix, ac_list, *, salience=0.9, confidence=0.9, causal_len=2):
    aas = [{"asset_class": ac, "direction": "positive"} for ac in ac_list]
    cc = [{"source": f"src_{i}", "target": f"tgt_{i}",
           "relation": "raises"} for i in range(causal_len)]
    return {
        "schema_version": "1.0.0",
        "claim_id": f"claim:2026-04:{suffix}",
        "period": "2026-04",
        "source_evidence_ids": ["ev1"],
        "supporting_evidence_ids": ["ev1"],
        "counter_evidence_ids": [],
        "claim_text": "테스트 청구문 sample text",
        "claim_type": "macro_to_asset",
        "affected_assets": aas,
        "causal_chain": cc,
        "direction": "positive",
        "horizon": "short",
        "confidence": confidence,
        "salience": salience,
        "linked_wiki_pages": [],
        "extractor_version": "r9a.1-haiku",
        "extraction_method": "llm",
        "warnings": [],
    }


def _agent_ctx_with_claims():
    """Minimum context for _build_agent_prompt with claims present."""
    claims = [_claim("aaaaaaaaaa", ["국내주식", "해외주식", "국내채권"])]
    claims_text = debate_engine._format_claims_for_context(claims)
    return {
        "year": 2026, "month": 4, "fund_code": None,
        "asset_movement_anchors_text": "## Asset Movement Anchors\n(생략)",
        "claims_text": claims_text,
        "news_summary_text": "(뉴스 데이터 없음)",
        "indicators_text": "(지표 없음)",
        "timeseries_narrative_text": "",
        "graph_paths_text": "",
        "wiki_context_text": "",
        "asset_coverage_text": "",
        "blog_context_text": "(없음)",
    }


# ──────────────────────────────────────────────────────────────────
# _build_agent_prompt
# ──────────────────────────────────────────────────────────────────

def test_agent_prompt_includes_claim_citation_instruction():
    ctx = _agent_ctx_with_claims()
    prompt = debate_engine._build_agent_prompt("bull", ctx)
    assert "## 필수: Canonical Claim 인용 규칙 (R9-A.3)" in prompt
    assert "[claim:hash10]" in prompt
    assert "[ref:N]" in prompt  # ref 와 claim 병기 가능 명시
    # 규칙: 사용 안 한 claim 강제 금지
    assert "억지로 인용하지" in prompt
    # 사용된 claim 의 hash10 이 prompt 에 등장 (Canonical Claims block 자체)
    assert "[claim:aaaaaaaaaa]" in prompt


def test_agent_prompt_no_citation_instruction_when_no_claims():
    ctx = _agent_ctx_with_claims()
    ctx["claims_text"] = ""  # 빈 claims_text 시나리오
    prompt = debate_engine._build_agent_prompt("bull", ctx)
    # claims block 자체가 없으면 citation rule 도 미부착
    assert "## 필수: Canonical Claim 인용 규칙 (R9-A.3)" not in prompt


def test_agent_prompt_citation_block_position_after_claims():
    ctx = _agent_ctx_with_claims()
    prompt = debate_engine._build_agent_prompt("bull", ctx)
    claims_pos = prompt.find("## Canonical Claims (R9-A.3, 참고용)")
    citation_pos = prompt.find("## 필수: Canonical Claim 인용 규칙 (R9-A.3)")
    news_pos = prompt.find("(뉴스 데이터 없음)")
    assert claims_pos >= 0
    assert citation_pos > claims_pos
    assert news_pos > citation_pos  # citation rule 은 news block 보다 앞에


# ──────────────────────────────────────────────────────────────────
# _synthesize_debate (synthesis prompt)
# ──────────────────────────────────────────────────────────────────

def test_synthesis_prompt_includes_claims_and_citation_instruction(monkeypatch):
    """_call_llm 을 monkey-patch 해 synthesis 의 comment_prompt 캡처."""
    captured_prompts: list[dict] = []

    def fake_call_llm(*, model, system, prompt, max_tokens, log_label,
                       **kwargs):
        captured_prompts.append({
            "model": model, "log_label": log_label,
            "prompt": prompt, "max_tokens": max_tokens,
        })
        # log_label 별 minimal valid response
        if log_label == "synthesis_step1_comment":
            return "synthesis comment text."
        if log_label == "synthesis_step2_analysis":
            return ('{"consensus_points":["c1"],"disagreements":[],'
                    '"tail_risks":[],"admin_summary":"a"}')
        return ""

    monkeypatch.setattr(debate_engine, "_call_llm", fake_call_llm)

    # context with claims_text — 가능한 한 작게.
    claims = [_claim("syntactic1", ["국내주식", "해외주식", "원자재금"])]
    claims_text = debate_engine._format_claims_for_context(claims)
    context = {
        "year": 2026, "month": 4, "fund_code": None,
        "claims_text": claims_text,
        "news_summary_text": "뉴스 요약 (테스트)",
        "graph_paths_text": "",
        "wiki_context_text": "",
        "asset_coverage_text": "",
        "_quarterly": False,
    }
    agent_responses = {
        "bull": {"stance": "bullish", "key_points": ["p1"], "risk_assessment": "r",
                  "asset_allocation_view": {}, "tail_risks": [], "reasoning": "x"},
    }

    debate_engine._synthesize_debate(agent_responses, None, context)

    # 두 LLM call 캡처 (comment + analysis)
    assert len(captured_prompts) == 2
    comment_prompt = next(p for p in captured_prompts
                          if p["log_label"] == "synthesis_step1_comment")["prompt"]

    # synthesis comment prompt 에 Canonical Claims block + citation rule 모두 포함
    assert "## Canonical Claims (R9-A.3, 참고용)" in comment_prompt
    assert "[claim:syntactic1]" in comment_prompt
    assert "## 필수: Canonical Claim 인용 규칙 (R9-A.3)" in comment_prompt
    assert "[claim:hash10]" in comment_prompt
    # 기존 ref 규칙도 함께 유지 (regression)
    assert "[ref:N]" in comment_prompt


def test_synthesis_prompt_skips_claims_when_empty(monkeypatch):
    """claims_text 가 빈 문자열이면 synthesis 도 citation rule 부착 X."""
    captured_prompts: list[dict] = []

    def fake_call_llm(*, model, system, prompt, max_tokens, log_label,
                       **kwargs):
        captured_prompts.append({"prompt": prompt, "log_label": log_label})
        if log_label == "synthesis_step1_comment":
            return "x."
        return '{"consensus_points":[],"disagreements":[],"tail_risks":[],"admin_summary":""}'

    monkeypatch.setattr(debate_engine, "_call_llm", fake_call_llm)
    context = {
        "year": 2026, "month": 4, "fund_code": None,
        "claims_text": "",  # empty
        "news_summary_text": "x",
        "_quarterly": False,
    }
    agent_responses = {
        "bull": {"stance": "bullish", "key_points": [], "risk_assessment": "",
                  "asset_allocation_view": {}, "tail_risks": [], "reasoning": ""},
    }
    debate_engine._synthesize_debate(agent_responses, None, context)

    comment_prompt = next(p for p in captured_prompts
                          if p["log_label"] == "synthesis_step1_comment")["prompt"]
    assert "## Canonical Claims (R9-A.3, 참고용)" not in comment_prompt
    assert "## 필수: Canonical Claim 인용 규칙 (R9-A.3)" not in comment_prompt
    # 기존 [ref:N] 인용 블록은 변함없이 유지
    assert "[ref:N]" in comment_prompt


# ──────────────────────────────────────────────────────────────────
# evidence_trace 회귀 — [ref:N] + [claim:hash10] 병기
# ──────────────────────────────────────────────────────────────────

def test_combined_ref_and_claim_extracted_from_same_text():
    text = (
        "WTI 가 19% 폭락하였습니다[ref:1][claim:de1729b413]. "
        "JP모건 CEO 의 인플레 고착 경고가 이어졌습니다[ref:5][claim:a79b6f699d]."
    )
    refs = evidence_trace.extract_refs(text)
    claim_refs = evidence_trace.extract_claim_refs(text)
    assert sorted(r["ref_idx"] for r in refs) == [1, 5]
    assert sorted(c["hash10"] for c in claim_refs) == [
        "a79b6f699d", "de1729b413"]


def test_strip_claim_refs_preserves_ref_tags():
    text = "사실 문장입니다[ref:3][claim:abc1234567]."
    out = evidence_trace.strip_claim_refs(text)
    assert "[claim:" not in out
    assert "[ref:3]" in out


def test_strip_refs_preserves_claim_tags():
    """기존 strip_refs 는 [ref:N] 만 제거 (claim 태그 보존 회귀)."""
    text = "사실 문장입니다[ref:3][claim:abc1234567]."
    out = evidence_trace.strip_refs(text)
    assert "[ref:" not in out
    assert "[claim:abc1234567]" in out
