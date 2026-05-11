# -*- coding: utf-8 -*-
"""R9-A.4 Commit 4 — write gate + 실 write 분기 + monitoring fields 회귀.

A~G 카테고리 (workorder §9). 운영 canonical/wiki/ledger 파일은 절대 수정
하지 않음 — 실 write 검증은 tmp_path monkeypatch 격리.

Invariants:
  - 운영 `data/claims/2026-04.json` 등 보호 파일 md5 변경 0
  - default OFF (ENABLE_CLAIM_EXTRACTION=False) 유지
  - --write-claims 미지정 시 write 0
  - out_of_band=True + --allow-out-of-band 미지정 시 write 0
  - target_suffix=None + --write-claims 시 write 0 (Q4=B)
"""
from __future__ import annotations

import json

import pytest

from market_research.pipeline import claim_extract_step as ces


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

_PROMOTABLE = {
    "schema_version": "1.0.0",
    "claim_id": "claim:2026-04:c4promo01a",
    "period": "2026-04",
    "source_evidence_ids": ["art_c4_a", "art_c4_b"],
    "claim_text": "C4 write gate 검증용 promote-eligible claim — 다자산군 영향.",
    "claim_type": "event_to_macro",
    "affected_assets": [
        {"asset_class": "국내주식", "direction": "positive"},
        {"asset_class": "해외주식", "direction": "positive"},
        {"asset_class": "국내채권", "direction": "negative"},
    ],
    "causal_chain": [
        {"source": "x", "target": "y", "relation": "raises"},
        {"source": "y", "target": "z", "relation": "supports"},
    ],
    "direction": "positive",
    "horizon": "short",
    "confidence": 0.9,
    "salience": 0.9,
    "supporting_evidence_ids": ["art_c4_a"],
    "counter_evidence_ids": [],
    "linked_wiki_pages": [],
    "extractor_version": "r9a.4-haiku",
    "extraction_method": "llm",
    "warnings": [],
}

_NON_PROMOTABLE = {
    **_PROMOTABLE,
    "claim_id": "claim:2026-04:c4nopromo01",
    "claim_text": "C4 non-promotable claim — A3/B 미달.",
    "affected_assets": [
        {"asset_class": "국내주식", "direction": "positive"},
    ],
    "causal_chain": [
        {"source": "x", "target": "y", "relation": "raises"},
    ],
    "supporting_evidence_ids": ["art_c4_n"],
}


def _evidence(n: int = 3) -> list[dict]:
    return [
        {"article_id": f"art_c4_{i}", "title": f"c4 fixture {i}",
         "source": "Reuters", "date": "2026-04-15", "topic": "지정학"}
        for i in range(n)
    ]


def _raw(claims: list[dict]) -> str:
    return json.dumps(claims, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────
# Helper: isolate write paths via monkeypatch
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_write_paths(tmp_path, monkeypatch):
    """claim_store + claim_pages 의 file 경로 상수를 tmp_path 로 격리.

    운영 파일에 어떤 변경도 가지 않도록 보장.
    """
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir = tmp_path / "08_Claims"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = claims_dir / "_promotion_quality.jsonl"

    monkeypatch.setattr(
        "market_research.analyze.claim_store.CLAIMS_DATA_DIR", claims_dir,
    )
    monkeypatch.setattr(
        "market_research.analyze.claim_store.PROMOTION_LEDGER_PATH",
        ledger_path,
    )
    monkeypatch.setattr(
        "market_research.wiki.claim_pages.CLAIMS_WIKI_DIR", wiki_dir,
    )
    return {
        "claims_dir": claims_dir,
        "wiki_dir": wiki_dir,
        "ledger_path": ledger_path,
    }


# ──────────────────────────────────────────────────────────────────
# A. default off
# ──────────────────────────────────────────────────────────────────

def test_c4_A_default_off_no_run_no_write():
    """flag 없이 호출 — Step 2.7 진입 0 / LLM 0 / write 0."""
    out = ces.step_claim_extract("2026-04")
    assert out["status"] == ces.STATUS_DISABLED
    assert out["enabled"] is False
    assert out["llm_calls"] == 0
    assert out["writes"] == 0
    assert out["write_allowed"] is False
    assert out["actually_saved"] == []


def test_c4_A_default_off_invariant_enable_flag_false():
    assert ces.ENABLE_CLAIM_EXTRACTION is False


# ──────────────────────────────────────────────────────────────────
# B. dry-run path (--enable-claim-extraction only)
# ──────────────────────────────────────────────────────────────────

def test_c4_B_dry_run_without_write_claims():
    """enabled=True + write_* 미지정 → plan/preview 생성 + write 0."""
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        llm_call=lambda p: _raw([_PROMOTABLE, _NON_PROMOTABLE,
                                  _NON_PROMOTABLE, _NON_PROMOTABLE]),
    )
    assert out["enabled"] is True
    assert out["llm_calls"] == 1
    assert out["writes"] == 0
    assert out["actually_saved"] == []
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "default_dry_run"
    assert out["plan"] is not None
    assert out["ledger_row_preview"] is not None
    # ledger preview: write_allowed=False / write_claims=False / dry_run=True
    preview = out["ledger_row_preview"]
    assert preview["write_allowed"] is False
    assert preview["write_claims"] is False
    assert preview["dry_run"] is True


# ──────────────────────────────────────────────────────────────────
# C. write allowed path (in-band rate + target_suffix + --write-claims)
# ──────────────────────────────────────────────────────────────────

def test_c4_C_write_allowed_in_band(isolated_write_paths):
    """in-band rate (40%) + target_suffix 지정 + write_* 3종 → 실 write 진행."""
    # 2 promote + 3 fail = 40% rate
    promo_extra = {
        **_PROMOTABLE,
        "claim_id": "claim:2026-04:c4cpromo02",
        "claim_text": "C4 in-band test promote claim 2 — 동일 promote schema.",
        "supporting_evidence_ids": ["art_c4_p2"],
    }
    fail_a3 = [{**_NON_PROMOTABLE,
                 "claim_id": f"claim:2026-04:c4cn{i:06d}",
                 "claim_text": f"C4 in-band test non-promote {i}.",
                 "supporting_evidence_ids": [f"art_c4_n{i}"]}
                for i in range(3)]
    promo = [_PROMOTABLE, promo_extra] + fail_a3
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-c4test",
        llm_call=lambda p: _raw(promo),
    )
    # G-1~G-13 모두 통과 → 실 write
    assert out["status"] == ces.STATUS_OK_PLAN_READY
    assert out["write_allowed"] is True
    assert out["write_block_reason"] is None
    assert out["writes"] >= 3  # canonical + wiki(>=1) + ledger
    kinds = {a["kind"] for a in out["actually_saved"]}
    assert {"canonical_store", "wiki_08_claims",
            "promotion_ledger"} <= kinds

    # 실 file 확인 — target_suffix 분리 path
    canonical_file = isolated_write_paths["claims_dir"] / "2026-04.r9a4-c4test.json"
    assert canonical_file.exists()
    # 운영 path (suffix 없는 file) 은 미생성 (Q4=B 보장)
    assert not (isolated_write_paths["claims_dir"] / "2026-04.json").exists()


# ──────────────────────────────────────────────────────────────────
# D. out_of_band blocked path
# ──────────────────────────────────────────────────────────────────

def test_c4_D_out_of_band_blocked(isolated_write_paths):
    """rate 100% / out_of_band=True + --allow-out-of-band 없음 → write 차단."""
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-d",
        allow_out_of_band=False,
        llm_call=lambda p: _raw([_PROMOTABLE]),
    )
    assert out["status"] == ces.STATUS_PROMOTION_OUT_OF_BAND
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "out_of_band_default_block"
    assert out["writes"] == 0
    assert out["actually_saved"] == []
    # warning 에 drift 메시지 노출
    assert any(
        "out-of-band" in w for w in out["ledger_row_preview"]["warnings"]
    )
    # 실 file 미생성
    assert not (isolated_write_paths["claims_dir"] / "2026-04.r9a4-d.json").exists()


# ──────────────────────────────────────────────────────────────────
# E. out_of_band allowed path
# ──────────────────────────────────────────────────────────────────

def test_c4_E_out_of_band_allowed(isolated_write_paths):
    """rate 100% + --allow-out-of-band → write 허용."""
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-e",
        allow_out_of_band=True,
        llm_call=lambda p: _raw([_PROMOTABLE]),
    )
    # status 는 여전히 OUT_OF_BAND (plan 사실 그대로), write_allowed=True
    assert out["status"] == ces.STATUS_PROMOTION_OUT_OF_BAND
    assert out["write_allowed"] is True
    assert out["write_block_reason"] is None
    assert out["writes"] >= 3
    # monitoring 정보 유지
    assert out["allow_out_of_band"] is True
    assert out["plan"]["out_of_band"] is True
    # 실 file 생성
    assert (isolated_write_paths["claims_dir"] / "2026-04.r9a4-e.json").exists()


# ──────────────────────────────────────────────────────────────────
# F. monthly cap pre-abort
# ──────────────────────────────────────────────────────────────────

def test_c4_F_monthly_cap_pre_abort(tmp_path, isolated_write_paths):
    """누적 cost > cap → LLM 호출 0, write 0."""
    ledger = tmp_path / "_promo_seed.jsonl"
    ledger.write_text(
        json.dumps({"period": "2026-04", "source": "daily_update_r9a4",
                     "extractor_version": "r9a.4-haiku", "cost_usd": 0.99},
                    ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-f",
        monthly_cap_usd=1.0,
        ledger_path_override=ledger,
        llm_call=lambda p: _raw([_PROMOTABLE]),
    )
    assert out["status"] == ces.STATUS_COST_CAP_MONTHLY_PRE_ABORT
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "monthly_cap_exceeded"
    assert out["llm_calls"] == 0
    assert out["writes"] == 0


# ──────────────────────────────────────────────────────────────────
# G. invalid / failure matrix overlay
# ──────────────────────────────────────────────────────────────────

def test_c4_G_invalid_present_blocks_write(isolated_write_paths):
    """F-3 partial_extraction (invalid > 0) → write 차단."""
    # 2 promote + 3 fail-A3 = 40% in-band + 1 invalid
    invalid = {
        "claim_type": "INVALID",
        "affected_assets": [{"asset_class": "국내주식",
                              "direction": "positive"}],
        "causal_chain": [{"source": "x", "target": "y", "relation": "raises"}],
        "direction": "positive", "horizon": "short",
        "confidence": 0.5, "salience": 0.5,
        "supporting_evidence_ids": ["art_inv"], "counter_evidence_ids": [],
    }
    promo2 = [_PROMOTABLE, {
        **_PROMOTABLE, "claim_id": "claim:2026-04:c4gP02000a",
        "claim_text": "C4 G test promo 2 — 다자산군 영향.",
        "supporting_evidence_ids": ["art_g2"],
    }]
    fail_a3 = [{**_NON_PROMOTABLE,
                 "claim_id": f"claim:2026-04:c4gn{i:06d}",
                 "claim_text": f"C4 G test fail-A3 {i}.",
                 "supporting_evidence_ids": [f"art_gn{i}"]}
                for i in range(3)]
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-g",
        llm_call=lambda p: _raw(promo2 + fail_a3 + [invalid]),
    )
    assert out["status"] == ces.STATUS_PARTIAL_EXTRACTION
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "invalid_present"
    assert out["writes"] == 0


def test_c4_G_runner_failure_blocks_write(isolated_write_paths):
    """F-1 (llm_api_failure) → write 0."""
    def _fail(p):
        raise RuntimeError("mock api failure")
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-gr",
        llm_call=_fail,
    )
    assert out["status"] == ces.STATUS_RUNNER_ABORTED
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "runner_aborted"
    assert out["writes"] == 0


def test_c4_G_missing_target_suffix_blocks_write(isolated_write_paths):
    """G-13 — target_suffix=None + --write-claims → 운영 덮어쓰기 차단 (Q4=B)."""
    # 2 promote + 3 fail-A3 = 40% in-band, plan OK 라도 suffix 없으면 차단
    promo2 = [_PROMOTABLE, {
        **_PROMOTABLE, "claim_id": "claim:2026-04:c4gms02000a",
        "claim_text": "C4 G test missing suffix promote 2 — 다자산군.",
        "supporting_evidence_ids": ["art_gms2"],
    }]
    fail_a3 = [{**_NON_PROMOTABLE,
                 "claim_id": f"claim:2026-04:c4gms{i:05d}",
                 "claim_text": f"C4 G test missing suffix fail {i}.",
                 "supporting_evidence_ids": [f"art_gmsn{i}"]}
                for i in range(3)]
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix=None,  # 명시 미지정
        llm_call=lambda p: _raw(promo2 + fail_a3),
    )
    assert out["status"] == ces.STATUS_OK_PLAN_READY  # plan 은 OK
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "missing_target_suffix"
    assert out["writes"] == 0
    # 운영 path 미생성 (Q4=B 보장)
    assert not (isolated_write_paths["claims_dir"] / "2026-04.json").exists()


# ──────────────────────────────────────────────────────────────────
# 추가 — monitoring fields 일관 노출
# ──────────────────────────────────────────────────────────────────

def test_c4_monitoring_fields_present_on_all_paths():
    """모든 분기에서 monitoring fields 가 일관되게 노출."""
    expected_fields = {
        "write_allowed", "write_block_reason", "allow_out_of_band",
        "write_claims", "candidate_count", "canonical_existing_conflict_count",
    }
    # default disabled
    out = ces.step_claim_extract("2026-04")
    assert expected_fields <= set(out.keys())
    # dry-run path
    out = ces.step_claim_extract(
        "2026-04", enabled=True, evidence_items=_evidence(3),
        llm_call=lambda p: _raw([_PROMOTABLE]),
    )
    assert expected_fields <= set(out.keys())