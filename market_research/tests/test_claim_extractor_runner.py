# -*- coding: utf-8 -*-
"""R9-A.4 Commit 2 — claim_extractor_runner 단위 회귀.

LLM 호출 0 — `llm_call` 인자 monkeypatch.
file write 0 — runner 자체가 write 하지 않음 (Commit 2 invariant).
"""
from __future__ import annotations

import json

from market_research.analyze import claim_extractor_runner as runner
from market_research.analyze.claim_extractor_prompt import (
    EXTRACTOR_VERSION, SOURCE, LLM_MODEL, MAX_TOKENS,
    build_extraction_prompt,
)


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _evidence(count: int = 5) -> list[dict]:
    out = []
    for i in range(count):
        out.append({
            "article_id": f"art{i:03d}",
            "title": f"테스트 기사 {i} 제목",
            "source": "Reuters",
            "date": f"2026-04-{(i % 28) + 1:02d}",
            "topic": "지정학",
            "_event_salience": 0.5 + 0.05 * i,
        })
    return out


_RAW_OK = json.dumps([
    {
        "claim_text": "이란 휴전 합의로 위험자산 회복",
        "claim_type": "event_to_macro",
        "affected_assets": [
            {"asset_class": "국내주식", "direction": "positive"},
            {"asset_class": "환율(FX)", "direction": "negative"},
            {"asset_class": "원자재금", "direction": "negative"},
        ],
        "causal_chain": [
            {"source": "geopolitical_de_escalation",
             "target": "risk_appetite", "relation": "raises"},
        ],
        "direction": "positive",
        "horizon": "short",
        "confidence": 0.92,
        "salience": 0.95,
        "supporting_evidence_ids": ["art000"],
        "counter_evidence_ids": [],
    },
    {
        "claim_text": "WTI 19% 폭락",
        "claim_type": "event_to_macro",
        "affected_assets": [
            {"asset_class": "원자재금", "direction": "negative"},
        ],
        "causal_chain": [
            {"source": "geopolitical_de_escalation",
             "target": "oil_price", "relation": "lowers"},
        ],
        "direction": "negative",
        "horizon": "short",
        "confidence": 0.90,
        "salience": 1.0,
        "supporting_evidence_ids": ["art001", "art002"],
        "counter_evidence_ids": [],
    },
], ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────
# 1 — prompt 생성
# ──────────────────────────────────────────────────────────────────

def test_build_extraction_prompt_keys():
    p = build_extraction_prompt("2026-04", _evidence(3))
    assert set(p.keys()) == {"system", "user", "model", "max_tokens"}
    assert p["model"] == LLM_MODEL
    assert p["max_tokens"] == MAX_TOKENS
    assert "Period: 2026-04" in p["user"]
    assert "[art000]" in p["user"]
    assert "asset_class:" in p["user"]
    assert "claim_type:" in p["user"]


# ──────────────────────────────────────────────────────────────────
# 2 — 정상 추출 (LLM monkeypatch)
# ──────────────────────────────────────────────────────────────────

def test_extract_claims_valid_parse_2_claims():
    out = runner.extract_claims(
        "2026-04", _evidence(5),
        llm_call=lambda p: _RAW_OK,
    )
    assert out["abort_reason"] is None
    assert len(out["claims"]) == 2
    assert len(out["invalid_claims"]) == 0
    # Metadata 포함
    for c in out["claims"]:
        assert c["extractor_version"] == EXTRACTOR_VERSION
        assert c["claim_id"].startswith("claim:2026-04:")
    assert out["extractor_version"] == EXTRACTOR_VERSION
    assert out["source"] == SOURCE
    assert out["dry_run"] is True


# ──────────────────────────────────────────────────────────────────
# 3 — Invalid claim 분리
# ──────────────────────────────────────────────────────────────────

def test_extract_claims_invalid_separated():
    bad = json.dumps([
        {
            "claim_text": "valid claim text content",
            "claim_type": "event_to_macro",
            "affected_assets": [
                {"asset_class": "국내주식", "direction": "positive"}
            ],
            "causal_chain": [
                {"source": "x", "target": "y", "relation": "raises"}
            ],
            "direction": "positive",
            "horizon": "short",
            "confidence": 0.9, "salience": 0.9,
            "supporting_evidence_ids": ["art000"],
            "counter_evidence_ids": [],
        },
        {
            "claim_text": "invalid claim — bad asset_class",
            "claim_type": "event_to_macro",
            "affected_assets": [
                {"asset_class": "INVALID_CLASS", "direction": "positive"}
            ],
            "causal_chain": [],
            "direction": "positive",
            "horizon": "short",
            "confidence": 0.9, "salience": 0.9,
            "supporting_evidence_ids": ["art001"],
            "counter_evidence_ids": [],
        },
    ], ensure_ascii=False)

    out = runner.extract_claims(
        "2026-04", _evidence(3),
        llm_call=lambda p: bad,
    )
    assert len(out["claims"]) == 1
    assert len(out["invalid_claims"]) == 1
    assert "errors" in out["invalid_claims"][0]


# ──────────────────────────────────────────────────────────────────
# 4 — Deterministic ID (R9-A.0 재사용)
# ──────────────────────────────────────────────────────────────────

def test_deterministic_claim_id():
    out1 = runner.extract_claims(
        "2026-04", _evidence(3), llm_call=lambda p: _RAW_OK,
    )
    out2 = runner.extract_claims(
        "2026-04", _evidence(3), llm_call=lambda p: _RAW_OK,
    )
    assert out1["claims"][0]["claim_id"] == out2["claims"][0]["claim_id"]
    assert out1["claims"][1]["claim_id"] == out2["claims"][1]["claim_id"]


# ──────────────────────────────────────────────────────────────────
# 5 — extractor_version + source 라벨 (모든 claim)
# ──────────────────────────────────────────────────────────────────

def test_extractor_version_source_labels():
    out = runner.extract_claims(
        "2026-04", _evidence(3), llm_call=lambda p: _RAW_OK,
    )
    for c in out["claims"]:
        assert c["extractor_version"] == "r9a.4-haiku"
        assert c.get("extraction_method") == "llm"
    assert out["source"] == "daily_update_r9a4"


# ──────────────────────────────────────────────────────────────────
# 6 — Cost cap pre-abort
# ──────────────────────────────────────────────────────────────────

def test_cost_cap_pre_abort():
    """cost_cap_usd 매우 작게 → 사전 추정에서 abort, LLM 호출 0."""
    called = []

    def _llm(p):
        called.append(1)
        return _RAW_OK

    out = runner.extract_claims(
        "2026-04", _evidence(5),
        cost_cap_usd=0.0000001,  # 거의 0
        llm_call=_llm,
    )
    assert called == []  # LLM 호출 0
    assert out["abort_reason"] == "cost_cap_exceeded_estimate"
    assert any("cost_cap_exceeded_estimate" in w for w in out["warnings"])
    assert out["claims"] == []


# ──────────────────────────────────────────────────────────────────
# 7 — LLM API 실패 graceful
# ──────────────────────────────────────────────────────────────────

def test_llm_api_failure_graceful():
    def _fail(p):
        raise RuntimeError("simulated network failure")

    out = runner.extract_claims(
        "2026-04", _evidence(5), llm_call=_fail,
    )
    assert out["abort_reason"] == "llm_api_failure"
    assert any("llm_api_failure" in w for w in out["warnings"])
    assert out["claims"] == []


# ──────────────────────────────────────────────────────────────────
# 8 — JSON 파싱 실패 graceful
# ──────────────────────────────────────────────────────────────────

def test_json_parse_failed():
    out = runner.extract_claims(
        "2026-04", _evidence(5),
        llm_call=lambda p: "not a json — random text",
    )
    assert out["abort_reason"] == "json_parse_failed"
    assert any("json_parse_failed" in w for w in out["warnings"])
    assert len(out["invalid_claims"]) == 1


# ──────────────────────────────────────────────────────────────────
# 9 — Empty evidence
# ──────────────────────────────────────────────────────────────────

def test_empty_evidence_no_op():
    called = []

    def _llm(p):
        called.append(1)
        return _RAW_OK

    out = runner.extract_claims("2026-04", [], llm_call=_llm)
    assert out["abort_reason"] == "no_evidence"
    assert called == []  # LLM 호출 0
    assert out["claims"] == []


def test_none_evidence_no_op():
    called = []
    out = runner.extract_claims(
        "2026-04", None, llm_call=lambda p: called.append(1) or _RAW_OK)
    assert out["abort_reason"] == "no_evidence"
    assert called == []


# ──────────────────────────────────────────────────────────────────
# 10 — dry-run write 0 (runner 자체가 write 하지 않음)
# ──────────────────────────────────────────────────────────────────

def test_dry_run_no_file_write(tmp_path, monkeypatch):
    """runner 호출이 어떤 파일도 생성하지 않음 — pwd / tmp 모두."""
    monkeypatch.chdir(tmp_path)
    files_before = list(tmp_path.iterdir())
    runner.extract_claims(
        "2026-04", _evidence(3), llm_call=lambda p: _RAW_OK,
    )
    files_after = list(tmp_path.iterdir())
    assert files_before == files_after


# ──────────────────────────────────────────────────────────────────
# 11 — JSON fenced response 처리 (```json ... ```)
# ──────────────────────────────────────────────────────────────────

def test_json_fenced_response_accepted():
    fenced = "```json\n" + _RAW_OK + "\n```"
    out = runner.extract_claims(
        "2026-04", _evidence(3), llm_call=lambda p: fenced,
    )
    assert out["abort_reason"] is None
    assert len(out["claims"]) == 2


# ──────────────────────────────────────────────────────────────────
# 12 — 0 retry 정책 (실패 시 1회만 호출)
# ──────────────────────────────────────────────────────────────────

def test_no_retry_on_failure():
    call_count = [0]

    def _fail(p):
        call_count[0] += 1
        raise RuntimeError("fail")

    out = runner.extract_claims(
        "2026-04", _evidence(3), llm_call=_fail,
    )
    assert call_count[0] == 1  # retry 0
    assert out["abort_reason"] == "llm_api_failure"
