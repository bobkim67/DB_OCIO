# -*- coding: utf-8 -*-
"""R9-A.3 — anchor.linked_claims + debate _format_claims_for_context.

LLM 호출 0. 운영 데이터 미접근 (asset_movement_anchor 는 indicators.csv 만,
debate 의 _format_claims_for_context 는 순수 함수).
"""
from __future__ import annotations

from market_research.report.asset_movement_anchor import (
    build_asset_movement_anchors, _filter_claims_for_asset,
)
from market_research.report.debate_engine import _format_claims_for_context


def _claim(*, suffix, asset_classes, salience=0.9, confidence=0.9,
           causal_len=1, claim_text="테스트 청구문 sample text",
           ctype="macro_to_asset", evidence=("ev1",)):
    aas = [{"asset_class": ac, "direction": "positive"}
           for ac in asset_classes]
    cc = [{"source": f"src_{i}", "target": f"tgt_{i}",
           "relation": "raises"} for i in range(causal_len)]
    return {
        "schema_version": "1.0.0",
        "claim_id": f"claim:2026-04:{suffix}",
        "period": "2026-04",
        "source_evidence_ids": list(evidence),
        "supporting_evidence_ids": list(evidence),
        "counter_evidence_ids": [],
        "claim_text": claim_text,
        "claim_type": ctype,
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


# ──────────────────────────────────────────────────────────────────
# _filter_claims_for_asset (anchor helper)
# ──────────────────────────────────────────────────────────────────

def test_filter_claims_for_asset_match():
    c = _claim(suffix="aaa1234567",
               asset_classes=["국내주식", "해외주식", "국내채권"])
    out = _filter_claims_for_asset([c], "해외주식")
    assert len(out) == 1
    item = out[0]
    assert item["claim_id"] == c["claim_id"]
    assert item["claim_text"] == c["claim_text"]
    assert item["claim_type"] == "macro_to_asset"
    assert item["confidence"] == 0.9
    assert item["salience"] == 0.9
    assert item["supporting_evidence_ids"] == ["ev1"]
    assert item["wiki_filename"] == "2026-04_claim_aaa1234567.md"
    assert item["wiki_path"] == "08_Claims/2026-04_claim_aaa1234567.md"


def test_filter_claims_for_asset_no_match():
    c = _claim(suffix="bbb1234567", asset_classes=["환율(FX)"])
    assert _filter_claims_for_asset([c], "원자재금") == []


def test_filter_claims_robust_to_none_or_empty():
    assert _filter_claims_for_asset(None, "국내주식") == []
    assert _filter_claims_for_asset([], "국내주식") == []
    assert _filter_claims_for_asset([{}], "국내주식") == []


# ──────────────────────────────────────────────────────────────────
# build_asset_movement_anchors with claims=...
# ──────────────────────────────────────────────────────────────────

def test_anchor_linked_claims_attached(tmp_path):
    csv_text = (
        "date,DXY,USDKRW,SP500_TR,MSCI_KOREA,GOLD,FED_UPPER,UST_7_10Y_TR,KAP_BOND_TR,HY_TR\n"
        "2026-04-01,103,1450,5500,90,2300,5.5,180,1000,500\n"
        "2026-04-30,104,1500,5400,87,2400,5.5,178,1010,505\n"
    )
    fp = tmp_path / "indicators.csv"
    fp.write_text(csv_text, encoding="utf-8")

    cl_eq = _claim(suffix="eq11111111",
                   asset_classes=["국내주식", "해외주식", "국내채권"])
    cl_fx = _claim(suffix="fx11111111", asset_classes=["환율(FX)"])

    anchors = build_asset_movement_anchors(
        period="2026-04",
        causal_paths=[],
        evidence_annotations=[],
        indicators_csv_path=fp,
        claims=[cl_eq, cl_fx],
    )
    by_ac = {a["asset_class"]: a for a in anchors["asset_movements"]}
    eq_linked = by_ac["국내주식"]["linked_claims"]
    assert len(eq_linked) == 1
    assert eq_linked[0]["claim_id"] == cl_eq["claim_id"]
    fx_linked = by_ac["환율(FX)"]["linked_claims"]
    assert len(fx_linked) == 1
    assert fx_linked[0]["claim_id"] == cl_fx["claim_id"]
    # 비매칭 자산군은 빈 list
    assert by_ac["원자재금"]["linked_claims"] == []


def test_anchor_no_claims_arg_keeps_linked_claims_empty(tmp_path):
    csv_text = (
        "date,DXY,USDKRW,SP500_TR,MSCI_KOREA,GOLD,FED_UPPER,UST_7_10Y_TR,KAP_BOND_TR,HY_TR\n"
        "2026-04-01,103,1450,5500,90,2300,5.5,180,1000,500\n"
        "2026-04-30,104,1500,5400,87,2400,5.5,178,1010,505\n"
    )
    fp = tmp_path / "indicators.csv"
    fp.write_text(csv_text, encoding="utf-8")
    anchors = build_asset_movement_anchors(
        period="2026-04",
        causal_paths=[],
        evidence_annotations=[],
        indicators_csv_path=fp,
        # claims= 미전달 (기존 호출자 회귀)
    )
    for a in anchors["asset_movements"]:
        assert a["linked_claims"] == []


# ──────────────────────────────────────────────────────────────────
# _format_claims_for_context (debate)
# ──────────────────────────────────────────────────────────────────

def test_claims_text_block_contains_claim_id_anchors():
    c1 = _claim(suffix="aaaaaaaaaa",
                asset_classes=["국내주식", "해외주식", "국내채권"],
                claim_text="JP모건 CEO 이란 전쟁 인플레 고착 경고")
    c2 = _claim(suffix="bbbbbbbbbb",
                asset_classes=["원자재금"],
                claim_text="브렌트유 141달러 2008년 이후 최고")
    block = _format_claims_for_context([c1, c2])
    assert "## Canonical Claims" in block
    assert "[claim:aaaaaaaaaa]" in block
    assert "[claim:bbbbbbbbbb]" in block
    assert "JP모건 CEO" in block
    assert "type: macro_to_asset" in block
    assert "confidence: 0.9" in block
    # supporting evidence
    assert "evidence_ids: ev1" in block
    # caveat
    assert "단정 결론" in block


def test_claims_text_empty_when_no_claims():
    assert _format_claims_for_context([]) == ''
    assert _format_claims_for_context(None) == ''


def test_claims_text_truncates_long_text():
    long = "가" * 300
    c = _claim(suffix="long111111", asset_classes=["국내주식"], claim_text=long)
    block = _format_claims_for_context([c], text_truncate=180)
    # claim_text 라인 (anchor 다음)
    line = next(ln for ln in block.splitlines()
                if ln.startswith("[claim:long111111]"))
    # anchor + 공백 + body — body 길이 ≤ 180 + ellipsis
    body = line.split("] ", 1)[1]
    assert len(body) <= 180
    assert "…" in body


def test_claims_text_max_claims_respected():
    items = [
        _claim(suffix=f"cap{i:07d}", asset_classes=["국내주식"])
        for i in range(15)
    ]
    block = _format_claims_for_context(items, max_claims=3)
    anchor_lines = [ln for ln in block.splitlines() if ln.startswith("[claim:")]
    assert len(anchor_lines) == 3
