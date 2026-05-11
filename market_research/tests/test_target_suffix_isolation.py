# -*- coding: utf-8 -*-
"""R9-A.4 Commit 4.1 — target_suffix 가 canonical/wiki/ledger 3종 write sink
모두에 적용되는지 격리 검증.

C4 초기 구현은 target_suffix 가 canonical 에만 적용되고 wiki + ledger 는
운영 경로에 직접 write 되는 누락이 있었음. 본 모듈은 그 누락이 해결되었는지
회귀로 잠금.

invariant:
  - target_suffix 미지정 → 운영 path 그대로 (기존 C4 동작 회귀 0)
  - target_suffix 지정 → 3 sink 모두 운영 path 와 분리된 별 file 로 write
  - 운영 wiki / ledger / canonical 경로는 어떠한 변경도 받지 않음
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_research.analyze import claim_store
from market_research.pipeline import claim_extract_step as ces
from market_research.wiki import claim_pages


# ──────────────────────────────────────────────────────────────────
# Path resolvers — unit 수준 격리 검증
# ──────────────────────────────────────────────────────────────────

def test_ledger_path_none_returns_operational():
    """target_suffix=None → 운영 PROMOTION_LEDGER_PATH 그대로."""
    assert claim_store._ledger_path(None) == claim_store.PROMOTION_LEDGER_PATH


def test_ledger_path_suffix_returns_separated():
    """target_suffix='r9a4-replay' → `_promotion_quality.r9a4-replay.jsonl`"""
    p = claim_store._ledger_path("r9a4-replay")
    assert p.name == "_promotion_quality.r9a4-replay.jsonl"
    assert p.parent == claim_store.CLAIMS_DATA_DIR


def test_ledger_path_invalid_suffix_raises():
    for bad in ("../escape", "with/slash", "with space", "", "../../etc"):
        with pytest.raises(ValueError):
            claim_store._ledger_path(bad)


def test_wiki_page_path_none_returns_operational():
    claim = {
        "period": "2026-04",
        "claim_id": "claim:2026-04:abcdef1234",
    }
    p = claim_pages._page_path(claim, target_suffix=None)
    assert p.name == "2026-04_claim_abcdef1234.md"


def test_wiki_page_path_suffix_returns_separated():
    claim = {
        "period": "2026-04",
        "claim_id": "claim:2026-04:abcdef1234",
    }
    p = claim_pages._page_path(claim, target_suffix="r9a4-replay")
    assert p.name == "2026-04_claim_abcdef1234.r9a4-replay.md"


def test_wiki_page_path_invalid_suffix_raises():
    claim = {"period": "2026-04", "claim_id": "claim:2026-04:abcdef1234"}
    for bad in ("../escape", "with/slash", "with space", ""):
        with pytest.raises(ValueError):
            claim_pages._page_path(claim, target_suffix=bad)


# ──────────────────────────────────────────────────────────────────
# End-to-end — step γ 분기에서 3 sink 모두 격리
# ──────────────────────────────────────────────────────────────────

_PROMOTABLE = {
    "schema_version": "1.0.0",
    "claim_id": "claim:2026-04:c41iso00001",
    "period": "2026-04",
    "source_evidence_ids": ["art_iso_a", "art_iso_b"],
    "claim_text": "C4.1 isolation test promote-eligible claim — 다자산군 영향.",
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
    "supporting_evidence_ids": ["art_iso_a"],
    "counter_evidence_ids": [],
    "linked_wiki_pages": [],
    "extractor_version": "r9a.4-haiku",
    "extraction_method": "llm",
    "warnings": [],
}

_NON_PROMOTABLE = {
    **_PROMOTABLE,
    "claim_id": "claim:2026-04:c41iso99999",
    "claim_text": "C4.1 isolation test non-promote.",
    "affected_assets": [
        {"asset_class": "국내주식", "direction": "positive"},
    ],
    "causal_chain": [
        {"source": "x", "target": "y", "relation": "raises"},
    ],
    "supporting_evidence_ids": ["art_iso_n"],
}


def _evidence(n: int = 3) -> list[dict]:
    return [
        {"article_id": f"art_iso_{i}", "title": f"iso fixture {i}",
         "source": "Reuters", "date": "2026-04-15", "topic": "지정학"}
        for i in range(n)
    ]


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """3 sink 의 운영 path 를 모두 tmp_path 로 monkeypatch.

    중요: 단순 tmp 격리 — 본 fixture 는 "운영 path 가 어떤 경로인지" 자체를
    바꿔 모든 write 가 tmp 로 들어가게 한다. target_suffix 분리 검증은 별도
    파일명으로 일어남.
    """
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    wiki_dir = tmp_path / "08_Claims"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = claims_dir / "_promotion_quality.jsonl"

    monkeypatch.setattr(
        "market_research.analyze.claim_store.CLAIMS_DATA_DIR", claims_dir)
    monkeypatch.setattr(
        "market_research.analyze.claim_store.PROMOTION_LEDGER_PATH",
        ledger_path)
    monkeypatch.setattr(
        "market_research.wiki.claim_pages.CLAIMS_WIKI_DIR", wiki_dir)
    return {
        "claims_dir": claims_dir,
        "wiki_dir": wiki_dir,
        "ledger_path": ledger_path,
    }


def test_c41_target_suffix_isolates_canonical(isolated_paths):
    """canonical: 운영 file `{period}.json` 미생성, suffix file 만 생성."""
    promo = [_PROMOTABLE,
             {**_PROMOTABLE, "claim_id": "claim:2026-04:c41iso00002",
              "claim_text": "C4.1 iso test promote 2 — 다자산군 영향.",
              "supporting_evidence_ids": ["art_iso_p2"]}]
    skip = [{**_NON_PROMOTABLE,
              "claim_id": f"claim:2026-04:c41ison{i:04d}",
              "claim_text": f"C4.1 iso test non-promote {i}.",
              "supporting_evidence_ids": [f"art_iso_n{i}"]}
             for i in range(3)]
    raw = json.dumps(promo + skip, ensure_ascii=False)

    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-replay",
        llm_call=lambda p: raw,
    )
    assert out["status"] == ces.STATUS_OK_PLAN_READY
    assert out["write_allowed"] is True
    # suffix file 생성
    suffix_file = isolated_paths["claims_dir"] / "2026-04.r9a4-replay.json"
    assert suffix_file.exists()
    # 운영 path 미생성
    assert not (isolated_paths["claims_dir"] / "2026-04.json").exists()


def test_c41_target_suffix_isolates_wiki(isolated_paths):
    """wiki: 운영 `{period}_claim_{h}.md` 미생성, `.r9a4-replay.md` 만."""
    promo = [_PROMOTABLE,
             {**_PROMOTABLE, "claim_id": "claim:2026-04:c41wiso0002",
              "claim_text": "C4.1 wiki iso test promote 2.",
              "supporting_evidence_ids": ["art_w_p2"]}]
    skip = [{**_NON_PROMOTABLE,
              "claim_id": f"claim:2026-04:c41wn{i:05d}",
              "claim_text": f"C4.1 wiki iso non-promote {i}.",
              "supporting_evidence_ids": [f"art_w_n{i}"]}
             for i in range(3)]
    raw = json.dumps(promo + skip, ensure_ascii=False)

    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-replay",
        llm_call=lambda p: raw,
    )
    assert out["write_allowed"] is True
    # promoted 만 wiki 에 — runner normalize 후 새 cid 가 생기므로 정확한
    # 파일명을 미리 알 수 없지만, 패턴으로 모두 .r9a4-replay.md 인지 확인.
    wiki_files = list(isolated_paths["wiki_dir"].glob("*.md"))
    assert len(wiki_files) >= 1, "wiki 파일 1개 이상 생성 예상"
    for f in wiki_files:
        assert f.name.endswith(".r9a4-replay.md"), (
            f"운영 path 침범 — {f.name} 가 suffix 분리 패턴 아님"
        )
    # 운영 패턴 (`.md` 끝 직전이 hash10 인 형태) 미생성
    operational = [f for f in wiki_files
                   if not f.name.endswith(".r9a4-replay.md")]
    assert operational == [], (
        f"운영 wiki path 침범: {operational}"
    )


def test_c41_target_suffix_isolates_ledger(isolated_paths):
    """ledger: 운영 `_promotion_quality.jsonl` 미생성, suffix 만 생성."""
    promo = [_PROMOTABLE,
             {**_PROMOTABLE, "claim_id": "claim:2026-04:c41liso0002",
              "claim_text": "C4.1 ledger iso test promote 2.",
              "supporting_evidence_ids": ["art_l_p2"]}]
    skip = [{**_NON_PROMOTABLE,
              "claim_id": f"claim:2026-04:c41ln{i:05d}",
              "claim_text": f"C4.1 ledger iso non-promote {i}.",
              "supporting_evidence_ids": [f"art_l_n{i}"]}
             for i in range(3)]
    raw = json.dumps(promo + skip, ensure_ascii=False)

    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix="r9a4-replay",
        llm_call=lambda p: raw,
    )
    assert out["write_allowed"] is True
    suffix_ledger = (
        isolated_paths["claims_dir"] / "_promotion_quality.r9a4-replay.jsonl"
    )
    assert suffix_ledger.exists(), "suffix ledger 미생성"
    # 운영 ledger 미생성
    assert not isolated_paths["ledger_path"].exists(), (
        "운영 ledger path 침범"
    )
    # suffix ledger row 1개 (이번 호출의 33-field row)
    rows = suffix_ledger.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    # Commit 4.1 — isolated_write=True 자동 도출
    assert row["isolated_write"] is True
    assert row["target_suffix"] == "r9a4-replay"


def test_c41_target_suffix_none_uses_operational_paths(isolated_paths):
    """target_suffix=None + --write-claims → G-13 missing_target_suffix 차단.

    G-13 이 None 을 차단하므로 사실상 None 으로는 실 write 가 발생하지 않는다.
    본 테스트는 그 차단을 회귀로 잠금 (운영 path 보호 안전망).
    """
    promo = [_PROMOTABLE]
    raw = json.dumps(promo, ensure_ascii=False)
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        write_canonical=True,
        write_wiki=True,
        write_ledger=True,
        target_suffix=None,  # 명시 미지정
        allow_out_of_band=True,
        llm_call=lambda p: raw,
    )
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "missing_target_suffix"
    # 어떤 sink 도 생성 안 됨
    assert not isolated_paths["ledger_path"].exists()
    assert list(isolated_paths["wiki_dir"].glob("*.md")) == []
    assert not (isolated_paths["claims_dir"] / "2026-04.json").exists()


def test_c41_dry_run_no_write_to_either_path(isolated_paths):
    """--write-claims 없으면 dry-run — 운영도 suffix 도 모두 무변화."""
    promo = [_PROMOTABLE]
    out = ces.step_claim_extract(
        "2026-04",
        enabled=True,
        evidence_items=_evidence(3),
        target_suffix="r9a4-replay",
        llm_call=lambda p: json.dumps(promo, ensure_ascii=False),
    )
    assert out["write_allowed"] is False
    assert out["write_block_reason"] == "default_dry_run"
    # 어떤 file 도 생성 0
    assert list(isolated_paths["claims_dir"].glob("*.json")) == []
    assert list(isolated_paths["wiki_dir"].glob("*.md")) == []
    assert not isolated_paths["ledger_path"].exists()


# ──────────────────────────────────────────────────────────────────
# Direct ledger / wiki write helper 격리 (unit 수준 추가 잠금)
# ──────────────────────────────────────────────────────────────────

def test_c41_append_ledger_with_suffix_writes_separate_file(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "market_research.analyze.claim_store.CLAIMS_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        "market_research.analyze.claim_store.PROMOTION_LEDGER_PATH",
        tmp_path / "_promotion_quality.jsonl")
    operational = tmp_path / "_promotion_quality.jsonl"
    suffix = tmp_path / "_promotion_quality.r9a4-replay.jsonl"

    claim_store.append_promotion_ledger({"k": "v"})  # 운영
    claim_store.append_promotion_ledger({"k": "v"}, target_suffix="r9a4-replay")

    assert operational.exists()
    assert suffix.exists()
    # 각 file row 1개
    assert len(operational.read_text(encoding="utf-8").splitlines()) == 1
    assert len(suffix.read_text(encoding="utf-8").splitlines()) == 1
