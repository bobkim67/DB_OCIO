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
    from market_research.analyze.claim_extractor import (
        serialize_claim, REQUIRED_FIELDS,
    )
    c = _valid_claim()
    s = serialize_claim(c)
    keys = list(s.keys())
    # REQUIRED_FIELDS 순서 보존
    expected_order = [k for k in REQUIRED_FIELDS if k in c]
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
