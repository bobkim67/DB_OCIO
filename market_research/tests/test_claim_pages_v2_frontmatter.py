# -*- coding: utf-8 -*-
"""Taxonomy v2 wiring — claim_pages frontmatter region×sector 조건부 출력.

값 없으면 키 생략(기존 claim 재렌더 시 불필요 drift 방지) / 값 있으면 emit +
wiki_context_pack_builder._parse_frontmatter 로 round-trip 파싱 가능.
LLM 0, IO 0 (문자열 렌더만).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.wiki import claim_pages  # noqa: E402
from market_research.analyze.claim_extractor import normalize_claim  # noqa: E402
from market_research.report.wiki_context_pack_builder import (  # noqa: E402
    _parse_frontmatter,
)


def _base_claim(**extra) -> dict:
    c = {
        "period": "2026-05",
        "claim_text": "달러 강세로 미국채 금리·원달러 환율 동반 상승",
        "claim_type": "macro_to_asset",
        "affected_assets": [
            {"asset_class": "해외채권", "direction": "negative"},
            {"asset_class": "환율(FX)", "direction": "positive"},
        ],
        "direction": "negative", "horizon": "short",
        "confidence": 0.85, "salience": 0.9,
        "supporting_evidence_ids": ["aa11bb22cc33"],
    }
    c.update(extra)
    return normalize_claim(c)


def test_frontmatter_omits_v2_keys_when_absent():
    """primary_asset/regions/sectors 없는 claim → frontmatter 에 키 미출력."""
    page = claim_pages._render_page(_base_claim(), "B")
    fm, _ = _parse_frontmatter(page)
    assert "primary_asset" not in fm
    assert "regions" not in fm
    assert "sectors" not in fm
    # affected_assets 도 claim 에 frontmatter 미지정 시(없으면) 출력되지만,
    # 이 claim 은 affected_assets 가 있으므로 emit 됨 (의도된 Phase R 동작)
    assert fm.get("affected_assets") == ["해외채권", "환율(FX)"]


def test_frontmatter_emits_v2_keys_when_present():
    c = _base_claim(
        primary_asset="해외채권",
        regions=["US", "GLOBAL"],
        sectors=["통화정책", "금리_채권"],
    )
    page = claim_pages._render_page(c, "A")
    fm, _ = _parse_frontmatter(page)
    assert fm.get("primary_asset") == "해외채권"
    assert fm.get("regions") == ["US", "GLOBAL"]
    assert fm.get("sectors") == ["통화정책", "금리_채권"]
    assert fm.get("affected_assets") == ["해외채권", "환율(FX)"]


def test_frontmatter_roundtrip_special_char_asset():
    """'환율(FX)' 괄호 포함 자산 → quoted scalar / flow-list round-trip."""
    c = _base_claim(primary_asset="환율(FX)")
    page = claim_pages._render_page(c, "B")
    fm, _ = _parse_frontmatter(page)
    assert fm.get("primary_asset") == "환율(FX)"


def test_render_page_still_has_required_frontmatter():
    """v2 키 추가가 기존 필수 frontmatter(claim_id/period/promotion_rule) 보존."""
    page = claim_pages._render_page(_base_claim(), "C")
    fm, _ = _parse_frontmatter(page)
    assert fm.get("type") == "claim"
    assert str(fm.get("claim_id", "")).startswith("claim:")
    assert fm.get("period") == "2026-05"
    assert fm.get("promotion_rule") == "C"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
