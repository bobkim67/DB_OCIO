# -*- coding: utf-8 -*-
"""Asset taxonomy adapters — article/claim → 표준 자산군·토픽·마일스톤.

balanced_selector(제네릭 알고리즘)에 주입할 gate별 key 콜백의 공통 도메인 어댑터.
news_classifier.ASSET_KEYS(_asset_impact_vector 키) → OCIO 7 핵심 자산군 매핑 +
국내/해외 region 보정(키워드) + record-high 마일스톤 감지.

LLM 0, IO 0 — 순수 함수.
"""
from __future__ import annotations

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
