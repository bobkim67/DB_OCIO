# -*- coding: utf-8 -*-
"""R9-A.0 회귀: normalized claim schema / validator / deterministic ID / JSONL.

LLM 호출 0. tmp_path 만 사용. 운영 데이터 무접근.
Phase 0 범위 — schema 형상 단일 source-of-truth 확정만 검증.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

def _valid_claim() -> dict:
    """Phase 0 baseline — schema-conformant minimal claim."""
    from market_research.analyze.claim_extractor import normalize_claim
    return normalize_claim({
        "period": "2026-04",
        "claim_text": "미-이란 휴전 합의로 KOSPI 6.87% 급등",
        "claim_type": "event_to_macro",
        "source_evidence_ids": ["a1b2c3d4e5f6", "b2c3d4e5f6a1"],
        "affected_assets": [
            {"asset_class": "국내주식", "direction": "positive"},
            {"asset_class": "해외주식", "direction": "positive"},
        ],
        "causal_chain": [
            {"source": "event:geopolitical_de_escalation",
             "target": "macro:risk_appetite",
             "relation": "raises"},
        ],
        "direction": "positive",
        "horizon": "short",
        "confidence": 0.85,
        "salience": 0.9,
        "supporting_evidence_ids": ["a1b2c3d4e5f6"],
    })


# ──────────────────────────────────────────────────────────────────
# 1. valid + required field 검증
# ──────────────────────────────────────────────────────────────────

def test_valid_claim_passes():
    from market_research.analyze.claim_extractor import validate_claim
    r = validate_claim(_valid_claim())
    assert r["valid"], r["errors"]
    assert r["errors"] == []


def test_missing_required_field_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    del c["claim_type"]
    r = validate_claim(c)
    assert not r["valid"]
    assert any("claim_type" in e for e in r["errors"])


def test_non_dict_input_fails():
    from market_research.analyze.claim_extractor import validate_claim
    r = validate_claim("not a dict")
    assert not r["valid"]
    assert any("must be a dict" in e for e in r["errors"])


# ──────────────────────────────────────────────────────────────────
# 2. taxonomy 검증
# ──────────────────────────────────────────────────────────────────

def test_invalid_asset_class_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["affected_assets"] = [{"asset_class": "INVALID_ASSET"}]
    r = validate_claim(c)
    assert not r["valid"]
    assert any("INVALID_ASSET" in e for e in r["errors"])


def test_string_form_asset_class_validated():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["affected_assets"] = ["INVALID"]
    r = validate_claim(c)
    assert not r["valid"]


def test_invalid_direction_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["direction"] = "skyrocket"
    r = validate_claim(c)
    assert not r["valid"]


def test_invalid_horizon_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["horizon"] = "eternal"
    r = validate_claim(c)
    assert not r["valid"]


def test_invalid_claim_type_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["claim_type"] = "story"
    r = validate_claim(c)
    assert not r["valid"]


def test_invalid_extraction_method_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["extraction_method"] = "telepathy"
    r = validate_claim(c)
    assert not r["valid"]


# ──────────────────────────────────────────────────────────────────
# 3. confidence / salience 0~1
# ──────────────────────────────────────────────────────────────────

def test_confidence_out_of_range_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["confidence"] = 1.5
    assert not validate_claim(c)["valid"]
    c["confidence"] = -0.1
    assert not validate_claim(c)["valid"]
    c["confidence"] = "high"
    assert not validate_claim(c)["valid"]


def test_salience_out_of_range_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["salience"] = 2.0
    assert not validate_claim(c)["valid"]


def test_confidence_at_boundary_passes():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["confidence"] = 0.0
    assert validate_claim(c)["valid"]
    c["confidence"] = 1.0
    assert validate_claim(c)["valid"]


# ──────────────────────────────────────────────────────────────────
# 4. Deterministic claim_id
# ──────────────────────────────────────────────────────────────────

def test_deterministic_id_stable_across_runs():
    """같은 입력 두 번 호출 → 같은 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id(
        "2026-04",
        "이란 휴전 합의로 KOSPI 급등",
        ["e1", "e2", "e3"],
        [{"asset_class": "국내주식"}, {"asset_class": "해외주식"}],
    )
    cid2 = compute_claim_id(
        "2026-04",
        "이란 휴전 합의로 KOSPI 급등",
        ["e1", "e2", "e3"],
        [{"asset_class": "국내주식"}, {"asset_class": "해외주식"}],
    )
    assert cid1 == cid2
    assert cid1.startswith("claim:2026-04:")
    # md5 hex 10자
    suffix = cid1.split(":")[2]
    assert len(suffix) == 10
    int(suffix, 16)  # hex 검증


def test_evidence_id_order_independent():
    """source_evidence_ids 순서가 달라도 같은 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "x", ["e1", "e2", "e3"], ["국내주식"])
    cid2 = compute_claim_id("2026-04", "x", ["e3", "e1", "e2"], ["국내주식"])
    cid3 = compute_claim_id("2026-04", "x", ["e2", "e3", "e1"], ["국내주식"])
    assert cid1 == cid2 == cid3


def test_evidence_id_dedupe_in_id():
    """중복 evidence id 도 dedup 후 ID 동일."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "x", ["e1", "e2"], ["국내주식"])
    cid2 = compute_claim_id("2026-04", "x", ["e1", "e2", "e1", "e2"], ["국내주식"])
    assert cid1 == cid2


def test_assets_order_independent():
    """affected_assets 순서가 달라도 같은 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "x", ["e1"], ["국내주식", "해외주식"])
    cid2 = compute_claim_id("2026-04", "x", ["e1"], ["해외주식", "국내주식"])
    assert cid1 == cid2


def test_assets_dict_and_string_forms_equivalent():
    """assets 가 dict 든 str 이든 asset_class 같으면 동일 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "x", ["e1"],
                            [{"asset_class": "국내주식"}])
    cid2 = compute_claim_id("2026-04", "x", ["e1"], ["국내주식"])
    assert cid1 == cid2


def test_different_text_different_id():
    """claim_text 가 달라지면 다른 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "이란 휴전", ["e1"], ["국내주식"])
    cid2 = compute_claim_id("2026-04", "이란 분쟁 격화", ["e1"], ["국내주식"])
    assert cid1 != cid2


def test_unicode_normalization_text():
    """NFKC 정규화 + whitespace squash 결과 같은 텍스트는 같은 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    # full-width space, leading/trailing/multiple internal whitespace
    cid1 = compute_claim_id("2026-04", "이란 휴전 합의", ["e1"], ["국내주식"])
    cid2 = compute_claim_id("2026-04", "  이란   휴전   합의  ", ["e1"], ["국내주식"])
    assert cid1 == cid2


def test_different_period_different_id():
    """period 가 다르면 다른 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid_apr = compute_claim_id("2026-04", "x", ["e1"], ["국내주식"])
    cid_may = compute_claim_id("2026-05", "x", ["e1"], ["국내주식"])
    assert cid_apr != cid_may
    assert "2026-04" in cid_apr
    assert "2026-05" in cid_may


# ──────────────────────────────────────────────────────────────────
# 4.5  R9-A.8 — Canonical claim identity 재설계
# ──────────────────────────────────────────────────────────────────

def test_r9a8_normalize_strips_trailing_punctuation():
    """trailing . / ! / ? / 한국어 마침표 제거 후 동일 ID."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "미국 금리 상승 우려", ["e1"],
                            ["국내채권"])
    cid2 = compute_claim_id("2026-04", "미국 금리 상승 우려.", ["e1"],
                            ["국내채권"])
    cid3 = compute_claim_id("2026-04", "미국 금리 상승 우려!", ["e1"],
                            ["국내채권"])
    cid4 = compute_claim_id("2026-04", "미국 금리 상승 우려…", ["e1"],
                            ["국내채권"])
    assert cid1 == cid2 == cid3 == cid4


def test_r9a8_normalize_squashes_multi_punctuation():
    """'..' / '!?!' 등 연속 punctuation → 단일로 squash."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "원유 급등", ["e1"], ["원자재금"])
    cid2 = compute_claim_id("2026-04", "원유 급등...", ["e1"], ["원자재금"])
    cid3 = compute_claim_id("2026-04", "원유 급등!!!!!", ["e1"], ["원자재금"])
    assert cid1 == cid2 == cid3


def test_r9a8_normalize_lowercases_english():
    """영문 대소문자 차이는 동일 ID — 한글 무영향."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid_lower = compute_claim_id("2026-04", "FOMC dovish 시그널",
                                  ["e1"], ["해외채권"])
    cid_upper = compute_claim_id("2026-04", "FOMC DOVISH 시그널",
                                  ["e1"], ["해외채권"])
    cid_mixed = compute_claim_id("2026-04", "fomc Dovish 시그널",
                                  ["e1"], ["해외채권"])
    assert cid_lower == cid_upper == cid_mixed


def test_r9a8_evidence_set_hash_order_dedupe_independent():
    """evidence_ids 순서 / 중복은 무영향 (기존 R9-A.0 회귀 재확인)."""
    from market_research.analyze.claim_extractor import compute_claim_id
    cid1 = compute_claim_id("2026-04", "x", ["e3", "e1", "e2", "e1"],
                             ["국내주식"])
    cid2 = compute_claim_id("2026-04", "x", ["e1", "e2", "e3"], ["국내주식"])
    assert cid1 == cid2


def test_r9a8_direction_horizon_claim_type_in_id():
    """direction / horizon / claim_type 이 다르면 다른 ID — 신규 kwarg 인자."""
    from market_research.analyze.claim_extractor import compute_claim_id
    base = ("2026-04", "x", ["e1"], ["국내주식"])
    cid0 = compute_claim_id(*base)
    cid_dir = compute_claim_id(*base, direction="positive")
    cid_hor = compute_claim_id(*base, horizon="short")
    cid_typ = compute_claim_id(*base, claim_type="risk")
    assert cid0 != cid_dir
    assert cid0 != cid_hor
    assert cid0 != cid_typ
    # 그러나 backward compat — kwargs 미지정 (defaults) 시 deterministic
    cid_again = compute_claim_id(*base)
    assert cid0 == cid_again


def test_r9a8_canonical_group_id_basic():
    """compute_canonical_group_id 출력 format 검증."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    gid = compute_canonical_group_id(
        "2026-04", "이란 휴전 합의로 KOSPI 급등", ["국내주식"],
    )
    assert gid.startswith("group:2026-04:")
    suffix = gid.split(":")[2]
    assert len(suffix) == 10
    int(suffix, 16)  # hex 검증


def test_r9a8_group_id_evidence_set_independent():
    """canonical_group_id 는 evidence 무관 — 같은 content → 같은 group."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    # evidence 인수 자체가 group_id signature 에 들어가지 않음 — affected_assets
    # 만 들어감.
    gid1 = compute_canonical_group_id(
        "2026-04", "미국 고용 호조로 위험선호 확대", ["해외주식"],
    )
    gid2 = compute_canonical_group_id(
        "2026-04", "미국 고용 호조로 위험선호 확대", ["해외주식"],
    )
    assert gid1 == gid2


def test_r9a8_group_id_assets_order_independent():
    """affected_assets 순서가 달라도 같은 group_id."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    gid1 = compute_canonical_group_id(
        "2026-04", "금리 충격으로 다중 자산 영향",
        ["국내채권", "해외채권", "해외주식"],
    )
    gid2 = compute_canonical_group_id(
        "2026-04", "금리 충격으로 다중 자산 영향",
        ["해외주식", "해외채권", "국내채권"],
    )
    assert gid1 == gid2


def test_r9a8_group_id_normalize_text():
    """group_id 도 normalize_claim_text 통과 — wording variance 흡수."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    gid_plain = compute_canonical_group_id(
        "2026-04", "FOMC 매파 시그널", ["해외채권"],
    )
    gid_period = compute_canonical_group_id(
        "2026-04", "FOMC 매파 시그널.", ["해외채권"],
    )
    gid_case = compute_canonical_group_id(
        "2026-04", "fomc 매파 시그널", ["해외채권"],
    )
    assert gid_plain == gid_period == gid_case


def test_r9a8_group_id_different_text_different_group():
    """다른 의미의 claim 은 다른 group_id."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    gid1 = compute_canonical_group_id(
        "2026-04", "금리 상승", ["해외채권"],
    )
    gid2 = compute_canonical_group_id(
        "2026-04", "달러 강세", ["환율(FX)"],
    )
    assert gid1 != gid2


def test_r9a8_group_id_different_period_different_group():
    """period 가 다르면 다른 group_id."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    gid_apr = compute_canonical_group_id("2026-04", "x", ["국내주식"])
    gid_may = compute_canonical_group_id("2026-05", "x", ["국내주식"])
    assert gid_apr != gid_may


def test_r9a8_normalize_claim_attaches_group_id():
    """normalize_claim() 통과 시 canonical_group_id 자동 부착."""
    from market_research.analyze.claim_extractor import normalize_claim
    c = normalize_claim({
        "period": "2026-04",
        "claim_text": "미국 금리 상승 → 채권 부담",
        "source_evidence_ids": ["e1"],
        "affected_assets": [{"asset_class": "국내채권"}],
    })
    assert "canonical_group_id" in c
    assert c["canonical_group_id"].startswith("group:2026-04:")
    # claim_id 도 부착
    assert c["claim_id"].startswith("claim:2026-04:")


def test_r9a8_normalize_preserves_existing_group_id():
    """기존 group_id 가 있으면 보존 (override X)."""
    from market_research.analyze.claim_extractor import normalize_claim
    existing = "group:2026-04:abcdef0123"
    c = normalize_claim({
        "period": "2026-04",
        "claim_text": "x",
        "canonical_group_id": existing,
    })
    assert c["canonical_group_id"] == existing


def test_r9a8_validate_unusual_group_id_format_warns():
    """canonical_group_id 가 'group:' prefix 아닐 때 warning 만 (error X)."""
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["canonical_group_id"] = "claim:2026-04:abcdef0123"   # 잘못된 prefix
    r = validate_claim(c)
    assert r["valid"], r["errors"]
    assert any("canonical_group_id" in w for w in r["warnings"])


def test_r9a8_validate_missing_group_id_no_warning():
    """canonical_group_id 가 아예 없으면 backward compat — no warning."""
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    # _valid_claim() 은 normalize_claim 통과 → group_id 자동 부착. 의도적으로
    # 제거해 옛 데이터 (R9-A.1) shape 시뮬레이션.
    c.pop("canonical_group_id", None)
    r = validate_claim(c)
    assert r["valid"], r["errors"]
    assert not any("canonical_group_id" in w for w in r["warnings"])


def test_r9a8_claim_id_includes_evidence_group_id_does_not():
    """워크오더 §정책 — claim_id 는 evidence 포함, group_id 는 evidence 무관."""
    from market_research.analyze.claim_extractor import (
        compute_claim_id, compute_canonical_group_id,
    )
    same_text = "x"
    same_assets = ["국내주식"]
    cid_e1 = compute_claim_id("2026-04", same_text, ["e1"], same_assets)
    cid_e2 = compute_claim_id("2026-04", same_text, ["e2"], same_assets)
    gid_e1 = compute_canonical_group_id("2026-04", same_text, same_assets)
    gid_e2 = compute_canonical_group_id("2026-04", same_text, same_assets)
    # evidence 만 다른 두 claim_id 는 달라야 함
    assert cid_e1 != cid_e2
    # 같은 content 의 group_id 는 동일
    assert gid_e1 == gid_e2


# ──────────────────────────────────────────────────────────────────
# 4.6  R9-A.10 — source_evidence_ids fallback 복구
# ──────────────────────────────────────────────────────────────────

def test_r9a10_fallback_copies_supporting_into_source_when_empty():
    """R9-A.4 운영 prompt 가 source_* 누락 시 supporting_* 로 fallback."""
    from market_research.analyze.claim_extractor import normalize_claim
    c = normalize_claim({
        "period": "2026-04",
        "claim_text": "x",
        "supporting_evidence_ids": ["e2", "e1"],   # raw input 순서 보존
        # source_evidence_ids 미지정 → setdefault [] → empty
    })
    # fallback 으로 supporting 의 copy 가 들어와야 함
    assert c["source_evidence_ids"] == ["e2", "e1"]
    # supporting 자체는 변경 X
    assert c["supporting_evidence_ids"] == ["e2", "e1"]


def test_r9a10_fallback_preserves_existing_source():
    """기존 source_evidence_ids 가 채워져 있으면 절대 덮어쓰지 않음."""
    from market_research.analyze.claim_extractor import normalize_claim
    c = normalize_claim({
        "period": "2026-04",
        "claim_text": "x",
        "source_evidence_ids": ["manual_evidence"],
        "supporting_evidence_ids": ["e1", "e2"],
    })
    # 기존 source 보존
    assert c["source_evidence_ids"] == ["manual_evidence"]
    # supporting 도 보존
    assert c["supporting_evidence_ids"] == ["e1", "e2"]


def test_r9a10_no_fallback_when_both_empty():
    """둘 다 비어있으면 source_evidence_ids 빈 list 유지 (sentinel hash 정상)."""
    from market_research.analyze.claim_extractor import (
        normalize_claim, _build_evidence_set_hash,
    )
    c = normalize_claim({
        "period": "2026-04",
        "claim_text": "x",
    })
    assert c["source_evidence_ids"] == []
    assert c["supporting_evidence_ids"] == []
    # evidence_set_hash 는 sentinel "empty"
    assert _build_evidence_set_hash(c["source_evidence_ids"]) == "empty"


def test_r9a10_fallback_explicit_empty_source_still_fills():
    """raw 에 `source_evidence_ids: []` 가 명시되어도 fallback 작동.

    R9-A.4 운영 Haiku 가 source_* 미명시 → normalize_claim 의 setdefault 가
    `[]` 채움 → fallback 이 supporting 으로 보강. 또는 Haiku 가 명시적으로
    `"source_evidence_ids": []` 출력해도 동일하게 fallback. 핵심 — supporting
    의 정보가 있는데 source 가 비어있는 경우만.
    """
    from market_research.analyze.claim_extractor import normalize_claim
    c = normalize_claim({
        "period": "2026-04",
        "claim_text": "x",
        "source_evidence_ids": [],
        "supporting_evidence_ids": ["e3"],
    })
    assert c["source_evidence_ids"] == ["e3"]


def test_r9a10_fallback_recovers_evidence_layer_in_claim_id():
    """워크오더 §test4 (R9-A.12 정의 갱신) — 같은 content + supporting 만
    다른 두 claim → fallback 후 claim_id distinct, group_id 도 distinct.

    R9-A.8 원래 의도는 group_id evidence-independent 였으나, R9-A.11 fresh
    N=5 검증에서 text-based group_id 가 wording variance 로 죽는 것 확인 →
    R9-A.12 에서 group_id 정의를 evidence/assets/dir 기반으로 변경. evidence
    가 다르면 group 도 distinct (과소병합 원칙).
    """
    from market_research.analyze.claim_extractor import normalize_claim
    same_payload = {
        "period": "2026-04",
        "claim_text": "이란 휴전 합의로 위험선호 확대",
        "affected_assets": [{"asset_class": "해외주식"}],
        "direction": "positive",
        "horizon": "short",
        "claim_type": "event_to_macro",
    }
    c1 = normalize_claim({
        **same_payload,
        "supporting_evidence_ids": ["e1", "e2"],
    })
    c2 = normalize_claim({
        **same_payload,
        "supporting_evidence_ids": ["e3", "e4"],
    })
    # R9-A.10 — source 가 supporting 의 copy 로 채워짐
    assert c1["source_evidence_ids"] == ["e1", "e2"]
    assert c2["source_evidence_ids"] == ["e3", "e4"]
    # evidence layer 가 distinct → claim_id 도 distinct
    assert c1["claim_id"] != c2["claim_id"]
    # R9-A.12 — group_id 도 distinct (evidence 가 산정에 포함됨, 과소병합)
    assert c1["canonical_group_id"] != c2["canonical_group_id"]


def test_r9a10_fallback_evidence_order_independent_after_copy():
    """워크오더 §test4 — 같은 supporting set (순서만 다름) → 같은 claim_id."""
    from market_research.analyze.claim_extractor import normalize_claim
    same_payload = {
        "period": "2026-04",
        "claim_text": "x",
        "affected_assets": ["국내주식"],
    }
    c1 = normalize_claim({
        **same_payload,
        "supporting_evidence_ids": ["e1", "e2", "e3"],
    })
    c2 = normalize_claim({
        **same_payload,
        "supporting_evidence_ids": ["e3", "e1", "e2"],
    })
    # supporting 순서 보존 (단순 copy)
    assert c1["source_evidence_ids"] == ["e1", "e2", "e3"]
    assert c2["source_evidence_ids"] == ["e3", "e1", "e2"]
    # 그러나 _build_evidence_set_hash 가 sorted+unique 처리 → claim_id 동일
    assert c1["claim_id"] == c2["claim_id"]


# ──────────────────────────────────────────────────────────────────
# 4.7  R9-A.12 — group_id 재정의: evidence/assets/dir 기반 deterministic
#                (text 폐기 — wording variance 회피)
# ──────────────────────────────────────────────────────────────────

def test_r9a12_group_id_same_evidence_different_wording_same_group():
    """**R9-A.12 핵심** — 같은 evidence + 같은 assets/dir/hor/type 이면
    wording 이 달라도 같은 group_id.

    Haiku run-to-run wording variance (R9-A.11 normalized_text Jaccard 0.0)
    가 group_id 에 영향을 주지 않아야 함.
    """
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    gid1 = compute_canonical_group_id(
        "2026-04",
        "미국 금리 상승은 채권에 부담",   # wording A
        ["해외채권"],
        source_evidence_ids=["e1", "e2"],
        direction="negative",
        horizon="short",
        claim_type="macro_to_asset",
    )
    gid2 = compute_canonical_group_id(
        "2026-04",
        "Fed의 매파적 스탠스가 채권 가격에 부담",   # wording B (전혀 다름)
        ["해외채권"],
        source_evidence_ids=["e1", "e2"],
        direction="negative",
        horizon="short",
        claim_type="macro_to_asset",
    )
    assert gid1 == gid2


def test_r9a12_group_id_different_evidence_different_group():
    """다른 evidence subset → 다른 group_id (과소병합 원칙)."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    common = {
        "claim_text": "x",
        "affected_assets": ["해외채권"],
        "direction": "negative",
        "horizon": "short",
        "claim_type": "macro_to_asset",
    }
    gid1 = compute_canonical_group_id(
        "2026-04", common["claim_text"], common["affected_assets"],
        source_evidence_ids=["e1", "e2"],
        direction=common["direction"], horizon=common["horizon"],
        claim_type=common["claim_type"],
    )
    gid2 = compute_canonical_group_id(
        "2026-04", common["claim_text"], common["affected_assets"],
        source_evidence_ids=["e3", "e4"],
        direction=common["direction"], horizon=common["horizon"],
        claim_type=common["claim_type"],
    )
    assert gid1 != gid2


def test_r9a12_group_id_evidence_order_dedupe_independent():
    """evidence_ids 순서/중복 무관 — sorted+unique 처리."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1", "e2", "e3"],
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e3", "e1", "e2", "e1"],
    )
    assert g1 == g2


def test_r9a12_group_id_different_assets_different_group():
    """같은 evidence + 다른 affected_assets → 다른 group_id."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["국내주식"],
        source_evidence_ids=["e1"],
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외주식"],
        source_evidence_ids=["e1"],
    )
    assert g1 != g2


def test_r9a14_g1_group_id_direction_diagnostic_only():
    """R9-A.14 G1 채택 — direction 은 diagnostic field. 같은 evidence + 같은
    assets 면 direction 이 달라도 같은 group_id.

    R9-A.13 sensitivity matrix 결과: direction split 8.3% (12 multi-claim
    bucket 중 1개). enum variance 의 주범 — group_id 산정에서 제거.
    """
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1"], direction="positive",
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1"], direction="negative",
    )
    # R9-A.14 — direction 은 diagnostic only, group_id 에 영향 X
    assert g1 == g2


def test_r9a14_g1_group_id_horizon_diagnostic_only():
    """R9-A.14 G1 — horizon 도 diagnostic only. R9-A.13 horizon split 25%."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1"], horizon="short",
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1"], horizon="long",
    )
    assert g1 == g2


def test_r9a14_g1_group_id_claim_type_diagnostic_only():
    """R9-A.14 G1 — claim_type 도 diagnostic only. R9-A.13 split 33% (최다)."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1"], claim_type="event_to_macro",
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1"], claim_type="risk",
    )
    assert g1 == g2


def test_r9a14_g1_all_enums_diagnostic_together():
    """R9-A.14 G1 — direction + horizon + claim_type 모두 달라도 같은 group_id
    (같은 evidence + 같은 assets 라면)."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "wording A", ["해외채권"],
        source_evidence_ids=["e1", "e2"],
        direction="positive", horizon="short", claim_type="event_to_macro",
    )
    g2 = compute_canonical_group_id(
        "2026-04", "wording B", ["해외채권"],
        source_evidence_ids=["e1", "e2"],
        direction="negative", horizon="long", claim_type="risk",
    )
    assert g1 == g2


def test_r9a14_g1_evidence_still_distinct():
    """R9-A.14 G1 — evidence_set 다르면 여전히 distinct (과소병합 원칙 유지)."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e1", "e2"],
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권"],
        source_evidence_ids=["e3", "e4"],
    )
    assert g1 != g2


def test_r9a14_g1_assets_still_distinct():
    """R9-A.14 G1 — affected_assets 다르면 여전히 distinct (자산군별 추적)."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["국내주식"],
        source_evidence_ids=["e1"],
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외주식"],
        source_evidence_ids=["e1"],
    )
    assert g1 != g2


def test_r9a14_g1_assets_order_independent():
    """R9-A.14 G1 — affected_assets 순서 무관 (sorted 처리)."""
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "x", ["국내채권", "해외채권"],
        source_evidence_ids=["e1"],
    )
    g2 = compute_canonical_group_id(
        "2026-04", "x", ["해외채권", "국내채권"],
        source_evidence_ids=["e1"],
    )
    assert g1 == g2


def test_r9a12_normalize_claim_attaches_evidence_aware_group_id():
    """normalize_claim 통과 시 evidence_set 가 group_id 에 자동 반영."""
    from market_research.analyze.claim_extractor import normalize_claim
    same_payload = {
        "period": "2026-04",
        "claim_text": "어떤 wording",
        "affected_assets": ["해외채권"],
        "direction": "negative",
        "horizon": "short",
        "claim_type": "macro_to_asset",
    }
    # R9-A.10 fallback 으로 source ← supporting copy → group_id 에 반영됨
    c1 = normalize_claim({
        **same_payload,
        "supporting_evidence_ids": ["a", "b"],
    })
    c2 = normalize_claim({
        **same_payload,
        "supporting_evidence_ids": ["a", "b"],
        "claim_text": "완전히 다른 wording 이지만 같은 evidence/assets/dir",
    })
    # 같은 evidence + 같은 assets/dir/hor/type → 같은 group_id
    assert c1["canonical_group_id"] == c2["canonical_group_id"]


def test_r9a12_no_evidence_falls_back_to_empty_sentinel():
    """evidence 가 없으면 sentinel 'empty' 로 evset_hash 통일 — 같은 group_id.

    과소병합 원칙은 evidence 가 있는 경우에만 의미. evidence 가 없는 (manual /
    fallback 부재) claim 들끼리는 같은 자산/dir 면 같은 group 으로 묶임 —
    의도된 동작.
    """
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id(
        "2026-04", "wording A", ["해외채권"],
        source_evidence_ids=None,
    )
    g2 = compute_canonical_group_id(
        "2026-04", "wording B", ["해외채권"],
        source_evidence_ids=[],
    )
    assert g1 == g2


def test_r9a12_backward_compat_positional_call():
    """compute_canonical_group_id(period, text, assets) 기존 호출 패턴 유지.

    source_evidence_ids 미지정 → empty sentinel → claim_text 무관 동일 group.
    R9-A.8 의 R9-A.8 group_id 6 tests 가 모두 이 패턴 — 회귀 보호.
    """
    from market_research.analyze.claim_extractor import (
        compute_canonical_group_id,
    )
    g1 = compute_canonical_group_id("2026-04", "anything", ["국내주식"])
    g2 = compute_canonical_group_id("2026-04", "different text", ["국내주식"])
    # text 무관, evidence 둘 다 default empty, assets 같음 → 같은 group
    assert g1 == g2
    # 그러나 assets 가 다르면 distinct
    g3 = compute_canonical_group_id("2026-04", "anything", ["해외주식"])
    assert g1 != g3


# ──────────────────────────────────────────────────────────────────
# 5. causal_chain 검증
# ──────────────────────────────────────────────────────────────────

def test_causal_chain_relation_warning_for_unusual():
    """relation 이 ALLOWED_RELATIONS 밖이면 warning (error 아님)."""
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["causal_chain"] = [
        {"source": "x", "target": "y", "relation": "DOES_NOT_EXIST"},
    ]
    r = validate_claim(c)
    assert r["valid"], r["errors"]
    assert any("relation" in w for w in r["warnings"])


def test_causal_chain_missing_field_fails():
    """causal_chain edge 의 source/target/relation 누락 → error."""
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["causal_chain"] = [{"source": "x"}]
    r = validate_claim(c)
    assert not r["valid"]
    assert any("missing field" in e for e in r["errors"])


def test_causal_chain_empty_field_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["causal_chain"] = [{"source": "", "target": "y", "relation": "raises"}]
    r = validate_claim(c)
    assert not r["valid"]


def test_causal_chain_non_dict_fails():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["causal_chain"] = ["not a dict"]
    r = validate_claim(c)
    assert not r["valid"]


# ──────────────────────────────────────────────────────────────────
# 6. supporting / linked / counter
# ──────────────────────────────────────────────────────────────────

def test_supporting_evidence_outside_source_warns():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["supporting_evidence_ids"] = ["NOT_IN_SOURCE_SET"]
    r = validate_claim(c)
    assert r["valid"]
    assert any("outside source_evidence_ids" in w for w in r["warnings"])


def test_linked_wiki_path_traversal_rejected():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["linked_wiki_pages"] = ["../../etc/passwd"]
    r = validate_claim(c)
    assert not r["valid"]
    assert any("invalid path" in e for e in r["errors"])


def test_linked_wiki_absolute_path_rejected():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["linked_wiki_pages"] = ["/etc/passwd"]
    r = validate_claim(c)
    assert not r["valid"]


def test_linked_wiki_drive_letter_rejected():
    """Windows drive letter (C:\\...) 거부."""
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["linked_wiki_pages"] = ["C:\\Windows\\System32"]
    r = validate_claim(c)
    assert not r["valid"]


def test_linked_wiki_relative_in_wiki_dir_passes():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["linked_wiki_pages"] = ["08_Claims/2026-04_claim_iran.md",
                                "01_Events/2026-04_event_iran.md"]
    r = validate_claim(c)
    assert r["valid"], r["errors"]


# ──────────────────────────────────────────────────────────────────
# 7. soft warning — empty / short
# ──────────────────────────────────────────────────────────────────

def test_empty_evidence_warns():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["source_evidence_ids"] = []
    c["supporting_evidence_ids"] = []
    r = validate_claim(c)
    assert r["valid"]
    assert any("empty" in w.lower() for w in r["warnings"])


def test_short_claim_text_warns():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["claim_text"] = "abc"
    r = validate_claim(c)
    assert r["valid"]
    assert any("short" in w.lower() for w in r["warnings"])


def test_long_claim_text_warns():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["claim_text"] = "x" * 600
    r = validate_claim(c)
    assert r["valid"]
    assert any("long" in w.lower() for w in r["warnings"])


def test_period_format_unusual_warns():
    from market_research.analyze.claim_extractor import (
        validate_claim, normalize_claim,
    )
    c = normalize_claim({**_valid_claim(), "period": "weird"})
    r = validate_claim(c)
    assert any("period" in w.lower() for w in r["warnings"])


# ──────────────────────────────────────────────────────────────────
# 8. normalize defaults
# ──────────────────────────────────────────────────────────────────

def test_normalize_fills_defaults_and_id():
    from market_research.analyze.claim_extractor import normalize_claim
    raw = {
        "period": "2026-04",
        "claim_text": "test claim sample",
        "claim_type": "outlook_view",
        "source_evidence_ids": ["e1"],
        "affected_assets": [{"asset_class": "국내주식"}],
        "confidence": 0.5,
        "salience": 0.5,
    }
    n = normalize_claim(raw)
    assert n["schema_version"] == "1.0.0"
    assert n["claim_id"].startswith("claim:2026-04:")
    assert n["direction"] == "unknown"
    assert n["horizon"] == "unknown"
    assert n["extractor_version"] == "r9a.0"
    assert n["extraction_method"] == "manual"
    assert n["warnings"] == []
    assert n["counter_evidence_ids"] == []
    assert n["linked_wiki_pages"] == []
    assert n["causal_chain"] == []


def test_normalize_preserves_existing_id():
    from market_research.analyze.claim_extractor import normalize_claim
    raw = {"claim_id": "claim:2026-04:custom123",
           "claim_text": "x", "period": "2026-04"}
    n = normalize_claim(raw)
    assert n["claim_id"] == "claim:2026-04:custom123"


def test_normalize_does_not_override_explicit_values():
    from market_research.analyze.claim_extractor import normalize_claim
    raw = {"period": "2026-04", "extraction_method": "llm",
           "direction": "negative", "horizon": "long"}
    n = normalize_claim(raw)
    assert n["extraction_method"] == "llm"
    assert n["direction"] == "negative"
    assert n["horizon"] == "long"


def test_normalize_handles_none_input():
    from market_research.analyze.claim_extractor import normalize_claim
    n = normalize_claim(None)
    assert n["schema_version"] == "1.0.0"
    assert n["period"] == "unknown"


# ──────────────────────────────────────────────────────────────────
# 9. JSONL roundtrip
# ──────────────────────────────────────────────────────────────────

def test_jsonl_roundtrip(tmp_path):
    from market_research.analyze.claim_extractor import (
        write_claims_jsonl, read_claims_jsonl,
    )
    claims = [_valid_claim(), _valid_claim()]
    fp = tmp_path / "subdir" / "claims.jsonl"  # parent auto-mkdir 검증
    out_path = write_claims_jsonl(fp, claims)
    assert out_path == fp
    loaded = read_claims_jsonl(fp)
    assert len(loaded) == 2
    assert loaded[0]["claim_id"] == claims[0]["claim_id"]
    assert loaded[0]["claim_text"] == claims[0]["claim_text"]
    # JSON 직렬화 안정성 — 한글 보존
    text = fp.read_text(encoding="utf-8")
    assert "이란" in text


def test_jsonl_read_missing_file_returns_empty(tmp_path):
    from market_research.analyze.claim_extractor import read_claims_jsonl
    fp = tmp_path / "does_not_exist.jsonl"
    assert read_claims_jsonl(fp) == []


def test_jsonl_path_traversal_rejected(tmp_path):
    from market_research.analyze.claim_extractor import write_claims_jsonl
    import pytest
    bad_path = tmp_path / ".." / "evil.jsonl"
    with pytest.raises(ValueError):
        write_claims_jsonl(bad_path, [])


# ──────────────────────────────────────────────────────────────────
# 10. serialize_claim 안정 키 순서
# ──────────────────────────────────────────────────────────────────

def test_serialize_claim_field_order():
    """REQUIRED_FIELDS 순서 보존 + R9-A.8 OPTIONAL_FIELDS 후행 보존."""
    from market_research.analyze.claim_extractor import (
        serialize_claim, REQUIRED_FIELDS, OPTIONAL_FIELDS,
    )
    c = _valid_claim()
    s = serialize_claim(c)
    keys = list(s.keys())
    # REQUIRED 먼저 (선언 순서), OPTIONAL 후행 (있을 때만)
    expected_order = [k for k in REQUIRED_FIELDS if k in c] + \
        [k for k in OPTIONAL_FIELDS if k in c]
    assert keys == expected_order


# ──────────────────────────────────────────────────────────────────
# 11. taxonomy 일관성 — R8-B 8 자산군과 동기화 확인
# ──────────────────────────────────────────────────────────────────

def test_allowed_asset_classes_match_r8b_anchor():
    """ALLOWED_ASSET_CLASSES 가 asset_movement_anchor 의 8 자산군과 동일."""
    from market_research.analyze.claim_extractor import ALLOWED_ASSET_CLASSES
    from market_research.report.asset_movement_anchor import ASSET_CLASSES_R8B
    assert set(ALLOWED_ASSET_CLASSES) == set(ASSET_CLASSES_R8B)


def test_taxonomy_constants_are_frozensets():
    """런타임 변경 방어 — frozenset 인지 확인."""
    from market_research.analyze import claim_extractor as ce
    for name in (
        "ALLOWED_ASSET_CLASSES", "ALLOWED_CLAIM_TYPES",
        "ALLOWED_DIRECTIONS", "ALLOWED_HORIZONS",
        "ALLOWED_RELATIONS", "ALLOWED_EXTRACTION_METHODS",
    ):
        assert isinstance(getattr(ce, name), frozenset), \
            f"{name} should be frozenset"


# ──────────────────────────────────────────────────────────────────
# 12. Taxonomy v2 wiring — OPTIONAL 필드 + _remap + md5 drift 0
# ──────────────────────────────────────────────────────────────────

def test_v2_optional_fields_absent_still_valid():
    """primary_asset/regions/sectors 없는 기존 claim → valid 불변."""
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    assert "primary_asset" not in c  # normalize 가 강제 부착 안 함
    r = validate_claim(c)
    assert r["valid"], r["errors"]


def test_v2_optional_fields_not_required():
    """REQUIRED_FIELDS 에 v2 필드 미포함 (md5 drift 방지 핵심)."""
    from market_research.analyze.claim_extractor import REQUIRED_FIELDS, OPTIONAL_FIELDS
    for f in ("primary_asset", "regions", "sectors"):
        assert f not in REQUIRED_FIELDS
        assert f in OPTIONAL_FIELDS


def test_v2_valid_optional_fields_pass():
    """valid primary_asset/regions/sectors → valid, region/sector warning 없음."""
    from market_research.analyze.claim_extractor import normalize_claim, validate_claim
    c = _valid_claim()
    c["primary_asset"] = "국내주식"
    c["regions"] = ["KR", "GLOBAL"]
    c["sectors"] = ["테크_AI_반도체", "지정학"]
    c = normalize_claim(c)
    r = validate_claim(c)
    assert r["valid"], r["errors"]
    assert not any("region invalid" in w for w in r["warnings"])
    assert not any("sector invalid" in w for w in r["warnings"])


def test_v2_invalid_primary_asset_warns_not_errors():
    """잘못된 primary_asset → warning, valid 유지 (soft)."""
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["primary_asset"] = "비트코인"  # 8-class 밖
    r = validate_claim(c)
    assert r["valid"], r["errors"]
    assert any("primary_asset" in w for w in r["warnings"])


def test_v2_invalid_region_sector_warn_not_error():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["regions"] = ["JP"]        # enum 밖
    c["sectors"] = ["존재안함"]   # taxonomy 밖
    r = validate_claim(c)
    assert r["valid"], r["errors"]
    assert any("region invalid" in w for w in r["warnings"])
    assert any("sector invalid" in w for w in r["warnings"])


def test_v2_role_count_warns():
    from market_research.analyze.claim_extractor import validate_claim
    c = _valid_claim()
    c["affected_assets"] = [
        {"asset_class": "국내주식", "direction": "positive", "role": "primary"},
        {"asset_class": "해외주식", "direction": "positive", "role": "primary"},
    ]
    r = validate_claim(c)
    assert r["valid"], r["errors"]
    assert any("role=primary count" in w for w in r["warnings"])


def test_v2_normalize_remaps_selector_label_to_8class():
    """normalize 가 selector label(환율/금대체) → 8-class 로 collapse."""
    from market_research.analyze.claim_extractor import normalize_claim, validate_claim
    c = normalize_claim({
        "period": "2026-05",
        "claim_text": "달러 강세로 환율·금 동반 상승",
        "claim_type": "macro_to_asset",
        "affected_assets": [
            {"asset_class": "환율", "direction": "positive"},   # selector label
            {"asset_class": "금대체", "direction": "positive"},  # selector label
        ],
        "primary_asset": "환율",
        "direction": "positive", "horizon": "short",
        "confidence": 0.8, "salience": 0.8,
        "supporting_evidence_ids": ["aa11bb22cc33"],
    })
    assert c["affected_assets"][0]["asset_class"] == "환율(FX)"
    assert c["affected_assets"][1]["asset_class"] == "대체"
    assert c["primary_asset"] == "환율(FX)"
    assert validate_claim(c)["valid"]


def test_v2_normalize_idempotent_on_8class_md5_drift_0():
    """이미 8-class 인 claim → normalize 가 claim_id/group_id/serialize 불변."""
    import hashlib, json
    from market_research.analyze.claim_extractor import normalize_claim, serialize_claim
    c1 = _valid_claim()
    before = hashlib.md5(
        json.dumps(serialize_claim(c1), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    cid_before, gid_before = c1["claim_id"], c1["canonical_group_id"]
    # 재-normalize (remap idempotent 검증)
    c2 = normalize_claim(c1)
    after = hashlib.md5(
        json.dumps(serialize_claim(c2), ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    assert c2["claim_id"] == cid_before
    assert c2["canonical_group_id"] == gid_before
    assert before == after  # serialize byte 동일 = md5 drift 0


def test_v2_serialize_excludes_absent_optional_fields():
    """신규 OPTIONAL 필드 미존재 claim → serialize 에 미포함 (기존 md5 보존)."""
    from market_research.analyze.claim_extractor import serialize_claim
    c = _valid_claim()
    s = serialize_claim(c)
    for f in ("primary_asset", "regions", "sectors"):
        assert f not in s


def test_v2_serialize_includes_present_optional_fields():
    from market_research.analyze.claim_extractor import normalize_claim, serialize_claim
    c = _valid_claim()
    c["primary_asset"] = "국내주식"
    c["regions"] = ["KR"]
    c["sectors"] = ["테크_AI_반도체"]
    s = serialize_claim(normalize_claim(c))
    assert s["primary_asset"] == "국내주식"
    assert s["regions"] == ["KR"]
    assert s["sectors"] == ["테크_AI_반도체"]


# ──────────────────────────────────────────────────────────────────
# P0 — research claim 전용 필드 (wiki_from_naver_research)
# ──────────────────────────────────────────────────────────────────

def _research_claim() -> dict:
    """naver_research 분해 claim — 기존 baseline + research OPTIONAL 필드."""
    c = _valid_claim()
    c["source_type"] = "naver_research"
    c["broker_author"] = "미래에셋증권"
    c["stance"] = "bullish"
    c["view"] = "반도체 비중확대"
    c["rationale_text"] = "AI capex 지속 + 메모리 업황 회복 기대"
    c["risk_factor"] = "중국 수요 둔화 시 하방"
    c["evidence_text"] = "2분기 가이던스 상향"
    return c


def test_research_claim_valid():
    from market_research.analyze.claim_extractor import validate_claim
    r = validate_claim(_research_claim())
    assert r["valid"], r["errors"]


def test_research_stance_invalid_is_warning_not_error():
    # stance 오류는 soft(warning) — 기존 claim valid 회귀 0 보장
    from market_research.analyze.claim_extractor import validate_claim
    c = _research_claim()
    c["stance"] = "VERY_BULLISH"
    r = validate_claim(c)
    assert r["valid"]
    assert any("stance invalid" in w for w in r["warnings"])


def test_research_source_type_invalid_is_warning():
    from market_research.analyze.claim_extractor import validate_claim
    c = _research_claim()
    c["source_type"] = "twitter"
    r = validate_claim(c)
    assert r["valid"]
    assert any("source_type invalid" in w for w in r["warnings"])


def test_stance_direction_decoupled_no_consistency_error():
    # 금리상승 전망: 채권 stance=bearish 이나 direction=positive — 일치강제 없음
    from market_research.analyze.claim_extractor import validate_claim
    c = _research_claim()
    c["stance"] = "bearish"
    c["direction"] = "positive"
    r = validate_claim(c)
    assert r["valid"]
    assert not any("stance" in w and "direction" in w for w in r["warnings"])


def test_research_free_text_field_type_warned():
    from market_research.analyze.claim_extractor import validate_claim
    c = _research_claim()
    c["view"] = 123  # str 아님
    r = validate_claim(c)
    assert r["valid"]
    assert any("view must be a string" in w for w in r["warnings"])


def test_research_fields_serialized():
    from market_research.analyze.claim_extractor import normalize_claim, serialize_claim
    s = serialize_claim(normalize_claim(_research_claim()))
    assert s["source_type"] == "naver_research"
    assert s["broker_author"] == "미래에셋증권"
    assert s["stance"] == "bullish"
    assert s["view"] == "반도체 비중확대"
    assert s["risk_factor"] == "중국 수요 둔화 시 하방"


def test_baseline_claim_omits_research_fields_md5_safe():
    # research 필드 없는 기존 claim → serialize 에 research 키 미주입 (md5 불변)
    from market_research.analyze.claim_extractor import (
        normalize_claim, serialize_claim, RESEARCH_OPTIONAL_FIELDS,
    )
    s = serialize_claim(normalize_claim(_valid_claim()))
    for k in RESEARCH_OPTIONAL_FIELDS:
        assert k not in s
