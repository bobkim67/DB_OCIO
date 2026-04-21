# -*- coding: utf-8 -*-
"""네이버 기사 URL → 원본 매체명 복원.

네이버 뉴스 수집 시 source가 "네이버검색"/"네이버금융"으로 일괄 설정되어
원본 매체명이 유실됨. URL 도메인에서 매체명을 복원한다.
"""
from urllib.parse import urlparse

# 도메인 → 매체명 매핑 (상위 40+ 도메인)
_DOMAIN_TO_SOURCE = {
    # TIER1 (salience source_quality 1.0)
    'yna.co.kr': '연합뉴스',
    'yonhapnewstv.co.kr': '연합뉴스TV',
    'newsis.com': '뉴시스',
    'news1.kr': '뉴스1',
    # TIER2 (salience source_quality 0.7)
    'mk.co.kr': '매일경제',
    'hankyung.com': '한국경제',
    'sedaily.com': '서울경제',
    'mt.co.kr': '머니투데이',
    'edaily.co.kr': '이데일리',
    'heraldcorp.com': '헤럴드경제',
    'chosun.com': '조선비즈',
    'etoday.co.kr': '이투데이',
    'einfomax.co.kr': '연합인포맥스',
    'view.asiae.co.kr': '아시아경제',
    'joongang.co.kr': '중앙일보',
    'donga.com': '동아일보',
    'sbs.co.kr': 'SBS',
    'ytn.co.kr': 'YTN',
    'wowtv.co.kr': '한국경제TV',
    'thebell.co.kr': '더벨',
    # TIER3 but with name
    'dt.co.kr': '디지털타임스',
    'digitaltoday.co.kr': '디지털투데이',
    'dailian.co.kr': '데일리안',
    'newdaily.co.kr': '뉴데일리',
    'metroseoul.co.kr': '메트로서울',
    'businesspost.co.kr': '비즈니스포스트',
    'econovill.com': '이코노믹리뷰',
    'ekn.kr': '에너지경제',
    'ebn.co.kr': 'EBN',
    'news2day.co.kr': '뉴스투데이',
    'pinpointco.kr': '핀포인트',
    'tokenpost.kr': '토큰포스트',
    'coinreaders.com': '코인리더스',
    'cbci.co.kr': 'CBCI',
}


def resolve_source_from_url(url: str, current_source: str = '') -> str:
    """URL 도메인에서 매체명을 복원. 매핑 없으면 원본 source 유지."""
    if current_source not in ('네이버검색', '네이버금융', ''):
        return current_source
    if not url:
        return current_source
    try:
        netloc = urlparse(url).netloc.lower()
        # www., biz., news., m. 등 서브도메인 제거
        for prefix in ('www.', 'biz.', 'news.', 'm.', 'view.'):
            if netloc.startswith(prefix) and netloc != prefix:
                # view.asiae.co.kr은 매핑에 포함되어 있으므로 원본 유지
                pass
        # 정확 매칭
        for domain, name in _DOMAIN_TO_SOURCE.items():
            if domain in netloc:
                return name
    except Exception:
        pass
    return current_source


def patch_articles_source(articles: list) -> int:
    """기사 리스트의 source를 URL 기반으로 일괄 복원. 변경 건수 반환."""
    count = 0
    for a in articles:
        old = a.get('source', '')
        if old in ('네이버검색', '네이버금융'):
            new = resolve_source_from_url(a.get('url', ''), old)
            if new != old:
                a['source'] = new
                count += 1
    return count
