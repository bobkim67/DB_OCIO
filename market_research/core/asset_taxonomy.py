# -*- coding: utf-8 -*-
"""Asset taxonomy adapters — article/claim → 표준 자산군·토픽·마일스톤.

balanced_selector(제네릭 알고리즘)에 주입할 gate별 key 콜백의 공통 도메인 어댑터.
news_classifier.ASSET_KEYS(_asset_impact_vector 키) → OCIO 7 핵심 자산군 매핑 +
국내/해외 region 보정(키워드) + record-high 마일스톤 감지.

LLM 0, IO 0 — 순수 함수.
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

# _asset_impact_vector / claim affected_assets 의 granular key → canonical 자산군
ASSET_IMPACT_TO_CANONICAL: dict[str, str] = {
    "국내주식": "국내주식",
    "해외주식": "해외주식", "미국주식_성장": "해외주식", "미국주식_가치": "해외주식",
    "국내채권": "국내채권",
    "해외채권": "해외채권", "해외채권_EM": "해외채권",
    "해외채권_USHY": "해외채권", "해외채권_USIG": "해외채권",
    "환율_USDKRW": "환율", "환율_DXY": "환율", "환율(FX)": "환율", "환율": "환율",
    "원자재_원유": "원자재에너지", "원자재": "원자재에너지",
    "원자재_금": "금대체", "원자재금": "금대체", "금/대체": "금대체", "금대체": "금대체",
    "현금성": "현금성", "크레딧": "크레딧",
}

# 국내 region 보정 키워드 (벡터 argmax 가 해외로 잡혀도 국내로 정정)
_KR_BOND_KW = ("한국은행", "한은", "금통위", "국고채", "기준금리", "통안채")
_KR_EQ_KW = ("코스피", "코스닥", "삼성전자", "sk하이닉스", "하이닉스", "밸류업", "팔천피", "8천피")


# ══════════════════════════════════════════
# Taxonomy v2 — region × sector 자산 라우팅 (MVP)
# ══════════════════════════════════════════
# region 을 1차 분류 차원으로 승격: asset = sector(성격) × route_by_region.
# 동일 sector 라도 region 이 국내/해외를 가른다 (테크 + KR → 국내주식, + US → 해외주식).
# dry 검증 logic (debug/claims/may2026_build/region_sector_dry_classify.py) 와 동일.

REGION_TAXONOMY = ("KR", "US", "NON_US_OVERSEAS", "GLOBAL", "UNKNOWN")
REGION_SET = frozenset(REGION_TAXONOMY)

# sector 성격 분류 — region 라우팅 대상 (주식성 / 금리성).
# cross-asset 글로벌 sector (환율/원자재/금/크레딧/크립토/지정학) 는 region 무관.
EQUITY_SECTORS = frozenset({"테크_AI_반도체", "경기_소비", "부동산"})
# 유동성_크레딧(HY/IG/사모신용) 도 금리성 — region 따라 국내/해외채권으로 라우팅
# (2026-06-17: 크레딧 독립 자산군 폐지. region 판단은 LLM 이 부여한 region 사용).
RATE_SECTORS = frozenset({"금리_채권", "통화정책", "물가_인플레이션", "유동성_크레딧"})
_OVERSEAS_REGIONS = frozenset({"US", "NON_US_OVERSEAS"})


def route_by_region(region: str | None, sector: str | None) -> str | None:
    """(region, sector) → OCIO canonical 자산군. 매핑 없으면 None.

    region-무관 cross-asset sector(환율/달러/에너지/금/크레딧/크립토)는 region 을
    무시하고 직접 매핑. 주식성/금리성 sector 는 region 으로 국내/해외를 가른다.

    §8 보정 (Phase R-1): rule fallback 은 보수적으로 — 다발성/모호 sector 는 None
    으로 두고 LLM affected_assets(hybrid resolver priority 1)에 위임한다.
    - 지정학 → None (원유·금·환율·주식·채권 전반 → 단일 고정 오류였음).
    - 관세_무역 → None (주식·물가·환율·금리·크레딧 다발).
    - GLOBAL + 주식성/금리성 → None (해외자산 default 가 해외로 새는 오분류였음).
      GLOBAL 은 region-free cross-asset sector 에만 직접 route.
    - UNKNOWN region 의 region-의존 sector 도 None.
    """
    # region-무관 cross-asset sector (region 무시 직접 매핑)
    if sector in ("환율_FX", "달러_글로벌유동성"):
        return "환율"
    if sector == "에너지_원자재":
        return "원자재에너지"
    if sector == "귀금속_금":
        return "금대체"
    if sector == "크립토":
        return "크립토"
    # 유동성_크레딧 은 RATE_SECTORS 로 이동 — 아래 region 라우팅(국내/해외채권)에서 처리.
    # 지정학·관세_무역 = 다발성 → rule fallback None (LLM affected_assets 위임). §8
    overseas = region in _OVERSEAS_REGIONS
    # 주식성 sector → 주식 (region 라우팅; KR/해외만, GLOBAL·UNKNOWN → None)
    if sector in EQUITY_SECTORS:
        if region == "KR":
            return "국내주식"
        if overseas:
            return "해외주식"
        return None  # GLOBAL / UNKNOWN → 라우팅 미정 (LLM 위임)
    # 금리성 sector → 채권 (region 라우팅; KR/해외만, GLOBAL·UNKNOWN → None)
    if sector in RATE_SECTORS:
        if region == "KR":
            return "국내채권"
        if overseas:
            return "해외채권"
        return None
    return None


# selector canonical label → claim 8-class(ALLOWED_ASSET_CLASSES) collapse (§1.A).
# route_by_region / article path 는 selector label space(환율·금대체·원자재에너지·크립토)
# 를 쓰지만 claim affected_assets 의 enum 은 8-class. claim 진입 경계에서만 collapse.
_REMAP_TO_8CLASS: dict[str, str] = {
    "국내주식": "국내주식", "해외주식": "해외주식",
    "국내채권": "국내채권", "해외채권": "해외채권",
    # 2026-06-17: 크레딧 폐지 → 해외채권 슬리브로 collapse (legacy/stray claim 안전망;
    # 신규 추출은 enum 에 크레딧 없어 LLM 이 region 따라 국내/해외채권 직접 배정).
    "크레딧": "해외채권",
    # 현금성 → 유동성, 원자재금/금대체/원자재에너지 → 대체 (라벨 변경).
    "현금성": "유동성", "유동성": "유동성",
    "환율": "환율(FX)", "환율(FX)": "환율(FX)",
    "금대체": "대체", "원자재에너지": "대체", "원자재금": "대체", "대체": "대체",
    # 크립토 = OCIO 자산 밖 → drop (claim 미승격). dict 미포함 → .get default None.
}


def _remap_to_8class(asset: str | None) -> str | None:
    """selector canonical label → claim 자산군 collapse (claim 진입 경계 전용).

    환율→환율(FX), 금대체·원자재에너지·원자재금→대체, 현금성→유동성, 크레딧→해외채권,
    크립토 및 매핑 밖 라벨 → None. 이미 운영 라벨이면 idempotent. selector article
    path 에는 적용 금지(label space 유지).
    """
    if not asset:
        return None
    return _REMAP_TO_8CLASS.get(asset)


# article/selector 진입 경계 collapse → balanced_selector.CORE_ASSETS(7) label space.
# route_by_region / LLM primary 는 selector 밖 라벨(크레딧·크립토·현금성)도 낼 수 있어,
# article path 출력이 CORE_ASSETS 계약을 벗어나는 label-space leakage 발생(R-4 발견).
# claim 진입부 _remap_to_8class 와 대칭이되 target label space 가 다르다:
#   - _remap_to_8class : claim 운영 라벨 (크레딧→해외채권·현금성→유동성·원자재금→대체, 크립토 drop)
#   - _remap_to_core_assets : selector 7-class (크레딧→해외채권, 크립토→금대체, 현금성 drop)
_REMAP_TO_CORE_ASSETS: dict[str, str] = {
    # CORE_ASSETS(7) — idempotent
    "국내주식": "국내주식", "해외주식": "해외주식",
    "국내채권": "국내채권", "해외채권": "해외채권",
    "환율": "환율", "원자재에너지": "원자재에너지", "금대체": "금대체",
    # selector 밖 라벨 → CORE 버킷 흡수
    "크레딧": "해외채권",   # 크레딧(HY/IG) → 해외채권 슬리브
    "크립토": "금대체",     # 크립토 → 대체투자(금대체)
    # 현금성 = selector(이벤트 선별) 대상 아님(직접 이벤트 제한·단독 비중결정 X) → drop.
    # dict 미포함 → .get default None. 매핑 밖 라벨도 동일하게 drop(strict, 누수 차단).
}


def _remap_to_core_assets(asset: str | None) -> str | None:
    """article 출력 → CORE_ASSETS(selector label space) collapse (article 진입 경계 전용).

    크레딧→해외채권, 크립토→금대체, 현금성 및 매핑 밖 라벨 → None(drop).
    이미 CORE_ASSETS 면 idempotent. claim path 에는 적용 금지(_remap_to_8class 사용).
    """
    if not asset:
        return None
    return _REMAP_TO_CORE_ASSETS.get(asset)

# Generic milestone lane — record-high/저 등 "긍정·완만해서 salience 저평가되는"
# 구조적 마일스톤 보조 rescue용. ★특정 지수 레벨(8000 등) 매직넘버 금지 — 일반
# record 표현 + 시장/지수 맥락 가드만 사용 (어느 지수/레벨이든 일반화).
# 단발 보조 slot 전용 (balanced coverage 를 압도하면 안 됨; selector milestone_slots 로 제한).
MILESTONE_PHRASE_KW = (
    "사상 최고", "사상 최저", "사상 첫", "신고가", "신저가",
    "역대 최고", "역대 최저", "역대 최초", "최고치", "최저치", "경신",
)
# 시장/지수 맥락 가드 (record 표현 단독 false positive 방지)
MILESTONE_CONTEXT_KW = (
    "코스피", "코스닥", "kospi", "지수", "증시", "나스닥", "s&p", "다우",
    "환율", "원/달러", "원·달러", "유가", "금값", "국채", "금리", "스프레드",
)


def _text(obj: dict) -> str:
    return (obj.get("title", "") + " " + (obj.get("description") or "")).lower()


def article_primary_asset(article: dict) -> str | None:
    """기사 _asset_impact_vector argmax → canonical 자산군 (+ 국내 region 보정).

    벡터 없으면 키워드 fallback. 매칭 없으면 None.
    """
    v = article.get("_asset_impact_vector")
    title = _text(article)
    if isinstance(v, dict) and v:
        agg: dict[str, float] = defaultdict(float)
        for k, val in v.items():
            canon = ASSET_IMPACT_TO_CANONICAL.get(k)
            if canon:
                try:
                    agg[canon] += abs(float(val))
                except (ValueError, TypeError):
                    continue
        if agg:
            best = max(agg, key=agg.get)
            if best in ("해외채권", "국내채권") and any(k in title for k in _KR_BOND_KW):
                return "국내채권"
            if best in ("해외주식", "국내주식") and any(k in title for k in _KR_EQ_KW):
                return "국내주식"
            return best
    if any(k in title for k in _KR_BOND_KW):
        return "국내채권"
    if any(k in title for k in _KR_EQ_KW):
        return "국내주식"
    return None


def article_primary_asset_v2(article: dict) -> str | None:
    """Taxonomy v2 hybrid 자산군 (설계 §5 resolve priority).

    priority 1) LLM 직접 primary `_primary_asset_v2`(research_v2 passthrough, 8-class)
       → ASSET_IMPACT_TO_CANONICAL 로 selector label 환원 후 반환.
    priority 2) `_classified_topics` per-topic (region, sector) route_by_region
       intensity 가중 argmax (selector label).
    priority 3) v1 article_primary_asset (벡터 argmax + KR 키워드).
    모든 출력은 _remap_to_core_assets 로 CORE_ASSETS(selector label space)에 collapse:
    크레딧→해외채권, 크립토→금대체, 현금성 및 매핑 밖 라벨→drop(None). label-space
    leakage(selector 7-class 밖 라벨 누수) 차단 (R-4 발견 / R-5 blocker).
    """
    # priority 1 — LLM 직접 primary (flag ON research_v2 에서만 부착됨)
    llm_pa = article.get("_primary_asset_v2")
    if llm_pa:
        mapped = _remap_to_core_assets(ASSET_IMPACT_TO_CANONICAL.get(llm_pa, llm_pa))
        if mapped:
            return mapped
        # 현금성 등 selector 밖 라벨 → drop 후 topic 라우팅으로 폴백

    ts = article.get("_classified_topics") or []
    agg: dict[str, float] = defaultdict(float)
    saw_region = False
    for t in ts:
        if not isinstance(t, dict):
            continue
        region = t.get("region")
        if region:
            saw_region = True
        sector = t.get("topic")
        # route 출력을 CORE label space 로 collapse 후 누적 (agg 는 CORE 라벨만 보유)
        asset = _remap_to_core_assets(route_by_region(region or "UNKNOWN", sector))
        if asset is None:
            continue
        try:
            w = abs(float(t.get("intensity", 5))) / 10.0
        except (ValueError, TypeError):
            w = 0.5
        agg[asset] += w
    if agg:
        return max(agg, key=agg.get)
    # region 정보가 없거나 라우팅이 전부 비면 v1 경로로 위임 (v1 도 CORE 로 collapse)
    if not saw_region:
        return _remap_to_core_assets(article_primary_asset(article))
    # region 은 있었으나 (UNKNOWN 등) 라우팅 미정 → 키워드 fallback 만 (CORE 라벨)
    title = _text(article)
    if any(k in title for k in _KR_BOND_KW):
        return "국내채권"
    if any(k in title for k in _KR_EQ_KW):
        return "국내주식"
    return None


def _region_v2_enabled() -> bool:
    """MR_RESEARCH_REGION_V2 flag (news_classifier._research_region_v2_enabled 동치).

    기본 OFF (shadow). 순수 env 읽기 — heavy import 회피 위해 여기 복제.
    """
    return os.getenv('MR_RESEARCH_REGION_V2', '').strip().lower() in (
        '1', 'true', 'on', 'yes')


def article_primary_asset_auto(article: dict) -> str | None:
    """flag-gate 디스패처 — OFF → v1 (route_by_region 미호출), ON → v2 routing.

    Phase W shadow 계약: MR_RESEARCH_REGION_V2 OFF 에서 article_primary_asset(v1)
    과 100% 동일. consumer(Gate2 등)는 본 함수만 호출해 v1/v2 분기를 단일화한다.
    """
    if _region_v2_enabled():
        return article_primary_asset_v2(article)
    return article_primary_asset(article)


def article_topic(article: dict) -> str:
    """기사 _classified_topics 의 첫 토픽 (topic CAP 키)."""
    ts = article.get("_classified_topics") or []
    if not ts:
        return "(none)"
    first = ts[0]
    if isinstance(first, dict):
        return first.get("topic") or "(none)"
    return str(first)


def article_is_milestone(article: dict) -> bool:
    """Generic record/마일스톤 기사 여부 (지수 신고가·신저가·사상 최고 등).

    record 표현(MILESTONE_PHRASE_KW) + 시장/지수 맥락(MILESTONE_CONTEXT_KW) 동시
    충족. 특정 레벨(8000 등) 숫자 매칭 없음 — 어느 지수/레벨이든 일반화.
    """
    t = _text(article)
    return (any(p in t for p in MILESTONE_PHRASE_KW)
            and any(c in t for c in MILESTONE_CONTEXT_KW))


def claim_primary_asset(claim: dict) -> str | None:
    """claim affected_assets 의 첫 자산군 → canonical."""
    aa = claim.get("affected_assets") or []
    if not aa:
        return None
    first = aa[0]
    name = first.get("asset_class") if isinstance(first, dict) else first
    return ASSET_IMPACT_TO_CANONICAL.get(name, name) if name else None
