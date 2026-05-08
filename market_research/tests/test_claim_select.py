# -*- coding: utf-8 -*-
"""R9-A.3 — Read-side claim selection helper.

LLM 호출 0. canonical store / wiki / ledger / report_output 미접근.
fixture 가 tmp_path 로 격리.
"""
from __future__ import annotations

import pytest

from market_research.analyze import claim_store
from market_research.analyze.claim_extractor import validate_claim


@pytest.fixture
def tmp_claims(tmp_path, monkeypatch):
    data_dir = tmp_path / "data_claims"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(claim_store, "CLAIMS_DATA_DIR", data_dir)
    monkeypatch.setattr(claim_store, "PROMOTION_LEDGER_PATH",
                        data_dir / "_promotion_quality.jsonl")
    return data_dir


def _claim(*, suffix, salience=0.9, confidence=0.9, assets=3,
           causal_chain=1, period="2026-04",
           text="테스트 청구문 sample text"):
    aas = [{"asset_class": ac, "direction": "positive"}
           for ac in ["국내주식", "해외주식", "국내채권", "해외채권"][:assets]]
    cc = [{"source": f"src_{i}", "target": f"tgt_{i}",
           "relation": "raises"} for i in range(causal_chain)]
    raw = {
        "schema_version": "1.0.0",
        "claim_id": f"claim:{period}:{suffix}",
        "period": period,
        "source_evidence_ids": ["ev1"],
        "supporting_evidence_ids": ["ev1"],
        "counter_evidence_ids": [],
        "claim_text": text,
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
    v = validate_claim(raw)
    assert v["valid"], v["errors"]
    return raw


# ──────────────────────────────────────────────────────────────────
# Missing store / empty inputs
# ──────────────────────────────────────────────────────────────────

def test_missing_store_returns_empty(tmp_claims):
    out = claim_store.select_promoted_claims_for_period("2026-04")
    assert out == []


def test_canonical_load_missing_returns_dict(tmp_claims):
    assert claim_store.load_claims_canonical("2026-04") == {}


# ──────────────────────────────────────────────────────────────────
# Promotion filter
# ──────────────────────────────────────────────────────────────────

def test_select_only_promoted(tmp_claims):
    promo_a = _claim(suffix="aaaaaaaaaa", assets=3, causal_chain=1)
    promo_b = _claim(suffix="bbbbbbbbbb", assets=1, causal_chain=2,
                     salience=0.5, confidence=0.5)
    skip_unmet = _claim(suffix="ccccccccc1", assets=1, causal_chain=1,
                        salience=0.5, confidence=0.5)
    claim_store.save_claims_canonical(
        period="2026-04",
        claims=[promo_a, promo_b, skip_unmet],
        source="test", extractor_version="r9a.1-haiku")

    out = claim_store.select_promoted_claims_for_period("2026-04")
    ids = [c["claim_id"] for c in out]
    assert promo_a["claim_id"] in ids
    assert promo_b["claim_id"] in ids
    assert skip_unmet["claim_id"] not in ids


# ──────────────────────────────────────────────────────────────────
# asset_class filter
# ──────────────────────────────────────────────────────────────────

def test_asset_class_filter(tmp_claims):
    # promo_a: 국내주식/해외주식/국내채권 (3 assets)
    promo_a = _claim(suffix="aaaaaaaaaa", assets=3)
    # 해외주식만 1개 → A 미만족, 그러나 causal_chain=2 로 B 통과
    promo_b_overseas_only = _claim(
        suffix="bbbbbbbbbb", assets=1, causal_chain=2,
        salience=0.5, confidence=0.5)
    # affected_assets 에 해외주식 미포함 (A 통과만)
    promo_c_no_overseas = {
        **_claim(suffix="ccccccccc2", assets=3),
        "affected_assets": [
            {"asset_class": "원자재금", "direction": "positive"},
            {"asset_class": "환율(FX)", "direction": "negative"},
            {"asset_class": "현금성", "direction": "neutral"},
        ],
    }
    # 해외주식 단독 (A,B 둘다 미만족)
    skip_overseas = _claim(suffix="dddddddd11", assets=1, causal_chain=1)

    claim_store.save_claims_canonical(
        period="2026-04",
        claims=[promo_a, promo_b_overseas_only, promo_c_no_overseas,
                skip_overseas],
        source="test", extractor_version="r9a.1-haiku")

    out = claim_store.select_promoted_claims_for_period(
        "2026-04", asset_class="해외주식")
    ids = [c["claim_id"] for c in out]
    # promo_b: '국내주식'만 1 asset → 해외주식 매칭 X. 다시 확인.
    # 위 _claim 의 assets=1 default 는 ["국내주식"][0:1] = "국내주식".
    # 즉 promo_b 는 해외주식 매칭 X → 빠짐. promo_a 만 매칭.
    assert promo_a["claim_id"] in ids
    assert promo_b_overseas_only["claim_id"] not in ids
    assert promo_c_no_overseas["claim_id"] not in ids
    assert skip_overseas["claim_id"] not in ids


# ──────────────────────────────────────────────────────────────────
# Ranking
# ──────────────────────────────────────────────────────────────────

def test_ranking_by_confidence_salience_then_causal_length(tmp_claims):
    # All pass A or B. ranking key: confidence*salience desc, causal_chain len desc
    high = _claim(suffix="hh11111111", assets=3, salience=0.9, confidence=0.9,
                  causal_chain=1)            # score = 0.81
    mid = _claim(suffix="mm11111111", assets=3, salience=0.8, confidence=0.8,
                 causal_chain=2)             # score = 0.64
    low_long_cc = _claim(suffix="ll11111111", assets=1, causal_chain=3,
                         salience=0.5, confidence=0.5)  # score=0.25, B pass

    claim_store.save_claims_canonical(
        period="2026-04",
        claims=[low_long_cc, mid, high],
        source="test", extractor_version="r9a.1-haiku")

    out = claim_store.select_promoted_claims_for_period("2026-04")
    assert [c["claim_id"] for c in out] == [
        high["claim_id"], mid["claim_id"], low_long_cc["claim_id"]]


# ──────────────────────────────────────────────────────────────────
# max_claims
# ──────────────────────────────────────────────────────────────────

def test_max_claims_cap(tmp_claims):
    items = [_claim(suffix=f"cap{i:07d}") for i in range(10)]
    claim_store.save_claims_canonical(
        period="2026-04", claims=items,
        source="test", extractor_version="r9a.1-haiku")

    out = claim_store.select_promoted_claims_for_period(
        "2026-04", max_claims=3)
    assert len(out) == 3


# ──────────────────────────────────────────────────────────────────
# Path helper
# ──────────────────────────────────────────────────────────────────

def test_claim_wiki_path():
    p = claim_store.claim_wiki_path("claim:2026-04:abc1234567")
    assert p == "08_Claims/2026-04_claim_abc1234567.md"


def test_claim_wiki_path_robust_to_bad_input():
    assert claim_store.claim_wiki_path(None) is None
    assert claim_store.claim_wiki_path("") is None
    assert claim_store.claim_wiki_path("not_a_claim_id") is None
    assert claim_store.claim_wiki_path("claim:onlypart") is None
