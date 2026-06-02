# -*- coding: utf-8 -*-
"""Taxonomy v2 (region × sector) MVP 단위 테스트. LLM 0, IO 0.

검증:
  - route_by_region: 동일 sector 라도 region 으로 국내/해외 분기 (테크 KR/US)
  - cross-asset sector 는 region 무관 (환율/원자재/금/크레딧/크립토/지정학)
  - REGION_SET / validate_regions / is_region 계약
  - article_primary_asset_v2: per-topic region 라우팅 argmax + v1 fallback
  - "팔천피" KR 테크 record → 국내주식 (v1 해외채권 오분류 해소)
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.core.asset_taxonomy import (  # noqa: E402
    REGION_SET, REGION_TAXONOMY, route_by_region,
    article_primary_asset, article_primary_asset_v2,
)
from market_research.wiki.taxonomy import (  # noqa: E402
    is_region, validate_regions, REGION_SET as WIKI_REGION_SET,
)


# ── region 라우팅: 주식성 sector × region ──

def test_equity_sector_region_split():
    # 동일 테크 sector 라도 region 이 자산을 가른다
    assert route_by_region("KR", "테크_AI_반도체") == "국내주식"
    assert route_by_region("US", "테크_AI_반도체") == "해외주식"
    assert route_by_region("NON_US_OVERSEAS", "테크_AI_반도체") == "해외주식"
    assert route_by_region("GLOBAL", "테크_AI_반도체") == "해외주식"  # 매크로 default
    assert route_by_region("UNKNOWN", "테크_AI_반도체") is None  # 보수적


def test_rate_sector_region_split():
    assert route_by_region("KR", "금리_채권") == "국내채권"
    assert route_by_region("US", "금리_채권") == "해외채권"
    assert route_by_region("KR", "통화정책") == "국내채권"
    assert route_by_region("US", "통화정책") == "해외채권"
    assert route_by_region("GLOBAL", "물가_인플레이션") == "해외채권"
    assert route_by_region("UNKNOWN", "금리_채권") is None


def test_tariff_routes_as_equity():
    # 관세_무역 = 글로벌 무역(위험자산) → 주식 region 라우팅
    assert route_by_region("KR", "관세_무역") == "국내주식"
    assert route_by_region("US", "관세_무역") == "해외주식"


def test_cross_asset_sectors_region_invariant():
    # cross-asset 글로벌 sector 는 region 무관 (어느 region 이든 동일)
    for region in REGION_TAXONOMY:
        assert route_by_region(region, "환율_FX") == "환율"
        assert route_by_region(region, "달러_글로벌유동성") == "환율"
        assert route_by_region(region, "에너지_원자재") == "원자재에너지"
        assert route_by_region(region, "귀금속_금") == "금대체"
        assert route_by_region(region, "유동성_크레딧") == "크레딧"
        assert route_by_region(region, "크립토") == "크립토"
        assert route_by_region(region, "지정학") == "원자재에너지"


def test_unknown_sector_returns_none():
    assert route_by_region("KR", "존재하지않는섹터") is None
    assert route_by_region("KR", None) is None


# ── region 계약 (wiki/taxonomy re-export) ──

def test_region_set_contract():
    assert REGION_SET == WIKI_REGION_SET
    assert "KR" in REGION_SET and "US" in REGION_SET
    assert "GLOBAL" in REGION_SET and "UNKNOWN" in REGION_SET
    assert is_region("KR") and not is_region("KOREA")


def test_validate_regions():
    valid, invalid = validate_regions(["KR", "US", "KR", "JP", ""])
    assert valid == ["KR", "US"]       # 중복 제거, 순서 유지
    assert invalid == ["JP"]           # enum 밖
    # UNKNOWN 도 valid enum
    v2, _ = validate_regions(["UNKNOWN"])
    assert v2 == ["UNKNOWN"]


# ── article_primary_asset_v2: per-topic region 라우팅 ──

def test_v2_kr_tech_to_domestic_equity():
    # "팔천피" 류: KR + 테크 → 국내주식 (v1 argmax 는 해외/매크로로 샜음)
    art = {
        "title": "국내 주식 마감 시황 - 마침내 팔천피",
        "description": "코스피가 사상 처음 8000을 넘었다. 반도체 강세 주도.",
        "_classified_topics": [
            {"region": "KR", "topic": "테크_AI_반도체", "direction": "positive", "intensity": 8},
            {"region": "GLOBAL", "topic": "지정학", "direction": "positive", "intensity": 4},
        ],
    }
    # v2: 테크 KR(국내주식, w0.8) vs 지정학(원자재에너지, w0.4) → 국내주식
    assert article_primary_asset_v2(art) == "국내주식"


def test_v2_us_tech_to_overseas_equity():
    art = {
        "title": "엔비디아 실적 서프라이즈",
        "description": "나스닥 급등.",
        "_classified_topics": [
            {"region": "US", "topic": "테크_AI_반도체", "direction": "positive", "intensity": 9},
        ],
    }
    assert article_primary_asset_v2(art) == "해외주식"


def test_v2_intensity_weighted_argmax():
    art = {
        "title": "x",
        "_classified_topics": [
            {"region": "KR", "topic": "테크_AI_반도체", "direction": "positive", "intensity": 3},
            {"region": "US", "topic": "금리_채권", "direction": "negative", "intensity": 9},
        ],
    }
    # 국내주식 w0.3 vs 해외채권 w0.9 → 해외채권
    assert article_primary_asset_v2(art) == "해외채권"


def test_v2_falls_back_to_v1_when_no_region():
    # region 필드 전혀 없는 v1 데이터 → article_primary_asset(v1) 위임
    art = {
        "title": "코스피 강세",
        "description": "",
        "_classified_topics": [{"topic": "테크_AI_반도체", "intensity": 7}],
        "_asset_impact_vector": {"해외주식": 0.8, "미국주식_성장": 0.9},
    }
    v1 = article_primary_asset(art)
    v2 = article_primary_asset_v2(art)
    assert v2 == v1  # 동일 (위임). _KR_EQ_KW(코스피) 보정으로 국내주식
    assert v2 == "국내주식"


def test_v2_region_present_but_unroutable_uses_keyword():
    # region 은 있으나 (UNKNOWN) 라우팅 미정 → KR 키워드 fallback
    art = {
        "title": "한국은행 기준금리 동결",
        "description": "",
        "_classified_topics": [
            {"region": "UNKNOWN", "topic": "테크_AI_반도체", "intensity": 5},
        ],
    }
    assert article_primary_asset_v2(art) == "국내채권"  # _KR_BOND_KW(한국은행)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
