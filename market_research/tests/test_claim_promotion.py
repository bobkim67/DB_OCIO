# -*- coding: utf-8 -*-
"""R9-A.2 — Tests for claim promotion + canonical store + guard.

LLM 호출 0. 운영 산출물 (report_output / approved / wiki 01~07) 미접근.
모든 wiki/data 쓰기는 monkeypatch 로 tmp_path 격리.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_research.analyze import claim_extractor as ce
from market_research.analyze import claim_store
from market_research.wiki import claim_pages
from market_research.wiki import draft_pages


# ──────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_wiki(tmp_path, monkeypatch):
    """Redirect 08_Claims/ + data/claims/ to tmp_path."""
    wiki_dir = tmp_path / "08_Claims"
    data_dir = tmp_path / "data_claims"
    wiki_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    monkeypatch.setattr(claim_pages, "CLAIMS_WIKI_DIR", wiki_dir)
    monkeypatch.setattr(claim_store, "CLAIMS_DATA_DIR", data_dir)
    monkeypatch.setattr(
        claim_store,
        "PROMOTION_LEDGER_PATH",
        data_dir / "_promotion_quality.jsonl",
    )
    return {"wiki": wiki_dir, "data": data_dir}


def _claim(*, salience=0.9, confidence=0.9, assets=3, causal_chain=1,
           text="테스트 청구문 sample text", evidence=("ev1",),
           cid_suffix="abc1234567"):
    # default assets=3 → R9-A.2 후속 Rule A3 (cross-asset threshold) 통과.
    aas = [{"asset_class": ac, "direction": "positive"}
           for ac in ["국내주식", "해외주식", "국내채권", "해외채권"][:assets]]
    cc = [{"source": f"src_{i}", "target": f"tgt_{i}", "relation": "raises"}
          for i in range(causal_chain)]
    period = "2026-04"
    cid = f"claim:{period}:{cid_suffix}"
    raw = {
        "schema_version": "1.0.0",
        "claim_id": cid,
        "period": period,
        "source_evidence_ids": list(evidence),
        "supporting_evidence_ids": list(evidence),
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
    v = ce.validate_claim(raw)
    assert v["valid"], v["errors"]
    return raw


# ──────────────────────────────────────────────────────────────────
# Promotion rules
# ──────────────────────────────────────────────────────────────────

def test_rule_a_alone_promoted(tmp_wiki):
    # A3: cross-asset (assets≥3). causal_chain=1 ensures B 미만족.
    c = _claim(salience=0.9, confidence=0.9, assets=3, causal_chain=1,
               cid_suffix="aaaaaaaaaa")
    r = claim_pages.promote_claims([c], rule="auto")
    assert r["promoted_count"] == 1
    assert r["rule_breakdown"]["A"] == 1
    assert (tmp_wiki["wiki"] / "2026-04_claim_aaaaaaaaaa.md").exists()


def test_rule_a_two_assets_no_longer_promoted(tmp_wiki):
    # A3 회귀 — 기존 A0 (assets≥2) 와 분기점 보호. assets=2 + causal=1 → skip.
    c = _claim(salience=0.95, confidence=0.95, assets=2, causal_chain=1,
               cid_suffix="a3regress1")
    r = claim_pages.promote_claims([c], rule="auto")
    assert r["promoted_count"] == 0
    assert r["skip_reasons"]["rule_a_b_unmet"] == 1


def test_rule_b_alone_promoted(tmp_wiki):
    # rule A 미만족 (single asset), rule B 만족 (causal_chain ≥ 2)
    c = _claim(salience=0.5, confidence=0.5, assets=1, causal_chain=2,
               cid_suffix="bbbbbbbbbb")
    r = claim_pages.promote_claims([c], rule="auto")
    assert r["promoted_count"] == 1
    assert r["rule_breakdown"]["B"] == 1


def test_rules_unmet_skipped(tmp_wiki):
    c = _claim(salience=0.5, confidence=0.5, assets=1, causal_chain=1,
               cid_suffix="ccccccccc1")
    r = claim_pages.promote_claims([c], rule="auto")
    assert r["promoted_count"] == 0
    assert r["skipped_count"] == 1
    assert r["skip_reasons"]["rule_a_b_unmet"] == 1


def test_force_promote_overrides_rules(tmp_wiki):
    c = _claim(salience=0.4, confidence=0.4, assets=1, causal_chain=1,
               cid_suffix="ddddddddd1")
    r = claim_pages.promote_claims(
        [c], rule="auto", force_ids=[c["claim_id"]])
    assert r["promoted_count"] == 1
    assert r["rule_breakdown"]["C"] == 1


# ──────────────────────────────────────────────────────────────────
# Idempotency / conflict
# ──────────────────────────────────────────────────────────────────

def test_idempotent_no_overwrite_same_evidence(tmp_wiki):
    c = _claim(cid_suffix="eeeeeeeeee", evidence=("ev1", "ev2"))
    r1 = claim_pages.promote_claims([c], rule="auto")
    assert r1["promoted_count"] == 1
    fp = tmp_wiki["wiki"] / "2026-04_claim_eeeeeeeeee.md"
    mtime1 = fp.stat().st_mtime_ns
    # second call → duplicate_existing skip
    r2 = claim_pages.promote_claims([c], rule="auto")
    assert r2["promoted_count"] == 0
    assert r2["skipped_count"] == 1
    assert r2["skip_reasons"]["duplicate_existing"] == 1
    assert fp.stat().st_mtime_ns == mtime1


def test_supporting_diff_existing_skipped(tmp_wiki):
    c = _claim(cid_suffix="fffffffff1", evidence=("ev1",))
    claim_pages.promote_claims([c], rule="auto")
    # 같은 claim_id 지만 supporting_evidence_ids 가 다름
    c2 = dict(c)
    c2["source_evidence_ids"] = ["ev1", "ev2"]
    c2["supporting_evidence_ids"] = ["ev1", "ev2"]
    r = claim_pages.promote_claims([c2], rule="auto")
    assert r["promoted_count"] == 0
    assert r["skip_reasons"]["supporting_diff_existing"] == 1


# ──────────────────────────────────────────────────────────────────
# Guards (08_Claims + draft_pages)
# ──────────────────────────────────────────────────────────────────

def test_is_claim_wiki_true(tmp_wiki):
    c = _claim(cid_suffix="9999999999")
    claim_pages.promote_claims([c], rule="auto")
    fp = tmp_wiki["wiki"] / "2026-04_claim_9999999999.md"
    assert claim_pages._is_claim_wiki(fp) is True


def test_is_enrichment_page_recognizes_claim_wiki(tmp_path):
    fp = tmp_path / "claim.md"
    fp.write_text(
        "---\ntype: claim\nsource_type: claim_wiki\n---\n# x\n",
        encoding="utf-8",
    )
    assert draft_pages._is_enrichment_page(fp) is True


# ──────────────────────────────────────────────────────────────────
# Canonical store
# ──────────────────────────────────────────────────────────────────

def test_canonical_save_load_roundtrip(tmp_wiki):
    c1 = _claim(cid_suffix="1111111111")
    c2 = _claim(cid_suffix="2222222222", text="다른 청구문 second sample text")
    out = claim_store.save_claims_canonical(
        period="2026-04",
        claims=[c1, c2],
        source="test",
        extractor_version="r9a.1-haiku",
        promotion_result={"promoted_count": 2, "skipped_count": 0},
    )
    assert out.exists()
    loaded = claim_store.load_claims_canonical("2026-04")
    assert loaded["period"] == "2026-04"
    assert loaded["schema_version"] == "1.0.0"
    assert len(loaded["claims"]) == 2
    assert loaded["stats"]["total"] == 2
    assert loaded["stats"]["promoted"] == 2
    assert "by_asset_class" in loaded["stats"]
    # claim_id deterministic 유지
    saved_ids = [c["claim_id"] for c in loaded["claims"]]
    assert c1["claim_id"] in saved_ids
    assert c2["claim_id"] in saved_ids


def test_missing_canonical_returns_empty_object(tmp_wiki):
    loaded = claim_store.load_claims_canonical("2099-12")
    assert loaded == {}


def test_canonical_save_rejects_invalid_claim(tmp_wiki):
    bad = _claim(cid_suffix="invalid001")
    bad["confidence"] = 999.0  # out of range
    with pytest.raises(ValueError):
        claim_store.save_claims_canonical(
            period="2026-04", claims=[bad],
            source="test", extractor_version="r9a.1-haiku")


def test_merge_prefer_higher_confidence(tmp_wiki):
    a = _claim(cid_suffix="merge12345", confidence=0.7)
    b = dict(a)
    b["confidence"] = 0.9
    b["claim_text"] = "high confidence variant text content"
    out = claim_store.merge_claims([a], [b],
                                    policy="prefer_higher_confidence")
    assert len(out) == 1
    assert out[0]["confidence"] == 0.9
    # tie/lower 시 기존 유지
    c = dict(a)
    c["confidence"] = 0.5
    out2 = claim_store.merge_claims([a], [c],
                                     policy="prefer_higher_confidence")
    assert out2[0]["confidence"] == 0.7


# ──────────────────────────────────────────────────────────────────
# Page rendering
# ──────────────────────────────────────────────────────────────────

def test_page_has_seven_body_sections(tmp_wiki):
    c = _claim(cid_suffix="sec1234567")
    claim_pages.promote_claims([c], rule="auto")
    fp = tmp_wiki["wiki"] / "2026-04_claim_sec1234567.md"
    text = fp.read_text(encoding="utf-8")
    for header in (
        "# ",  # heading
        "## Summary",
        "## Affected Assets",
        "## Causal Chain",
        "## Evidence",
        "## Linked Wiki",
        "## Metadata",
    ):
        assert header in text, f"missing section: {header!r}"
    # frontmatter
    assert "type: claim" in text
    assert "source_type: claim_wiki" in text
    assert "promotion_rule: A" in text


def test_long_claim_text_heading_truncated(tmp_wiki):
    long_text = "가" * 200
    c = _claim(cid_suffix="long123456", text=long_text)
    claim_pages.promote_claims([c], rule="auto")
    fp = tmp_wiki["wiki"] / "2026-04_claim_long123456.md"
    text = fp.read_text(encoding="utf-8")
    # heading line is truncated to ≤ 120 chars + ellipsis
    heading_line = next(ln for ln in text.splitlines()
                        if ln.startswith("# "))
    heading_body = heading_line[2:]
    assert "…" in heading_body
    assert len(heading_body) <= claim_pages.CLAIM_HEADING_MAX_LEN
    # full text preserved in Summary
    assert long_text in text


def test_linked_wiki_path_traversal_blocked(tmp_wiki):
    # validator 가 거르기 때문에 promote_claims 진입 자체 안 됨 →
    # writer 의 2차 방어를 직접 확인 (validator 우회 시뮬레이션).
    c = _claim(cid_suffix="lwk1234567")
    rendered = claim_pages._render_page(c, "A")
    assert "(없음)" in rendered  # default 빈 list

    # 직접 _render_linked_wiki 에 위험 path 주입
    bad = dict(c)
    bad["linked_wiki_pages"] = [
        "../../etc/passwd",
        "/abs/path",
        "C:\\windows",
        "01_Events/2026-04_event_x.md",  # 정상
    ]
    lines = claim_pages._render_linked_wiki(bad)
    joined = "\n".join(lines)
    assert ".." not in joined
    assert "/abs/path" not in joined
    assert "C:\\windows" not in joined
    assert "01_Events/2026-04_event_x.md" in joined


# ──────────────────────────────────────────────────────────────────
# Empty / no-op
# ──────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────
# CLI out-of-band write guard (R9-A.2 review feedback)
# ──────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, claims: list[dict]) -> None:
    ce.write_claims_jsonl(path, [ce.serialize_claim(c) for c in claims])


def test_cli_dry_run_out_of_band_succeeds_no_write(tmp_wiki, tmp_path):
    # 100% promotion (1/1) — out of band [30,70].
    c = _claim(cid_suffix="oob1111111")
    src = tmp_path / "claims.jsonl"
    _write_jsonl(src, [c])

    rc = claim_pages.main([
        "promote", "--period", "2026-04",
        "--from", str(src), "--dry-run",
    ])
    assert rc == 0
    assert not (tmp_wiki["wiki"] / "2026-04_claim_oob1111111.md").exists()
    assert not (tmp_wiki["data"] / "2026-04.json").exists()
    assert not (tmp_wiki["data"] / "_promotion_quality.jsonl").exists()


def test_cli_live_out_of_band_aborts_without_flag(tmp_wiki, tmp_path):
    c = _claim(cid_suffix="oob2222222")
    src = tmp_path / "claims.jsonl"
    _write_jsonl(src, [c])

    with pytest.raises(SystemExit) as exc:
        claim_pages.main([
            "promote", "--period", "2026-04", "--from", str(src),
        ])
    msg = str(exc.value)
    assert "ABORT" in msg
    assert "promotion_rate" in msg
    assert "input_count" in msg
    assert "promoted_count" in msg
    assert "allowed_band" in msg
    # 어떤 file 도 write 되어선 안 됨
    assert not (tmp_wiki["wiki"] / "2026-04_claim_oob2222222.md").exists()
    assert not (tmp_wiki["data"] / "2026-04.json").exists()
    assert not (tmp_wiki["data"] / "_promotion_quality.jsonl").exists()


def test_cli_live_out_of_band_with_allow_flag_proceeds(tmp_wiki, tmp_path):
    c = _claim(cid_suffix="oob3333333")
    src = tmp_path / "claims.jsonl"
    _write_jsonl(src, [c])

    rc = claim_pages.main([
        "promote", "--period", "2026-04", "--from", str(src),
        "--allow-out-of-band",
    ])
    assert rc == 0
    assert (tmp_wiki["wiki"] / "2026-04_claim_oob3333333.md").exists()
    assert (tmp_wiki["data"] / "2026-04.json").exists()
    ledger = (tmp_wiki["data"] / "_promotion_quality.jsonl").read_text(
        encoding="utf-8")
    rows = [json.loads(ln) for ln in ledger.splitlines() if ln.strip()]
    assert rows[-1]["out_of_band_override"] is True


def test_cli_in_band_live_proceeds_without_flag(tmp_wiki, tmp_path):
    # 1 promoted (A3 pass: assets=3) / 1 skipped → 50% rate, in band.
    c_pass = _claim(salience=0.9, confidence=0.9, assets=3,
                     causal_chain=1, cid_suffix="band111111")
    c_skip = _claim(salience=0.4, confidence=0.4, assets=1,
                     causal_chain=1, cid_suffix="band222222")
    src = tmp_path / "claims.jsonl"
    _write_jsonl(src, [c_pass, c_skip])

    rc = claim_pages.main([
        "promote", "--period", "2026-04", "--from", str(src),
    ])
    assert rc == 0
    assert (tmp_wiki["wiki"] / "2026-04_claim_band111111.md").exists()
    assert not (tmp_wiki["wiki"] / "2026-04_claim_band222222.md").exists()
    assert (tmp_wiki["data"] / "2026-04.json").exists()
    ledger = (tmp_wiki["data"] / "_promotion_quality.jsonl").read_text(
        encoding="utf-8")
    rows = [json.loads(ln) for ln in ledger.splitlines() if ln.strip()]
    assert rows[-1]["promoted_count"] == 1
    assert rows[-1]["skipped_count"] == 1
    assert rows[-1]["out_of_band_override"] is False


def test_empty_claims_input_no_op_and_ledger(tmp_wiki):
    r = claim_pages.promote_claims([], rule="auto")
    assert r["input_count"] == 0
    assert r["promoted_count"] == 0
    # ledger row append 가능 — 호출 측에서 결정
    claim_store.append_promotion_ledger({
        "ts": "2026-05-08T00:00:00",
        "period": "2026-04",
        "input_count": 0,
        "promoted_count": 0,
        "skipped_count": 0,
    })
    ledger = (tmp_wiki["data"] / "_promotion_quality.jsonl").read_text(
        encoding="utf-8")
    assert ledger.strip()
    rows = [json.loads(ln) for ln in ledger.splitlines()]
    assert rows[-1]["input_count"] == 0
