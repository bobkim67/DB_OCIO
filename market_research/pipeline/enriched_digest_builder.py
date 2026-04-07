# -*- coding: utf-8 -*-
"""
Enriched Digest Builder
========================
블로그 digest의 key_claims/key_events를 뉴스 벡터DB로 교차검증하여
각 토픽에 corroborating_news(뒷받침 뉴스)를 첨부한 enriched digest 생성.

사용법:
    python -m market_research.enriched_digest_builder 2026 3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.stdout and sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
DIGEST_DIR = BASE_DIR / 'data' / 'monygeek' / 'monthly_digests'
ENRICHED_DIR = BASE_DIR / 'data' / 'enriched_digests'

# 토픽 → 영문 검색 쿼리 매핑 (뉴스DB가 영문 위주)
TOPIC_QUERY_MAP = {
    '금리': 'interest rate Federal Reserve bond yield Treasury',
    '달러': 'US dollar DXY strength weakness currency',
    '이민_노동': 'US labor market immigration employment',
    '물가': 'inflation CPI PCE consumer prices stagflation',
    '관세': 'tariff trade war protectionism import duty',
    '안전자산': 'safe haven gold Treasury flight to safety',
    '미국채': 'US Treasury bond yield curve term premium',
    '엔화_캐리': 'Japanese yen carry trade BOJ interest rate',
    '중국_위안화': 'China yuan renminbi PBOC stimulus',
    '유로달러': 'eurodollar liquidity offshore dollar funding',
    '유가_에너지': 'oil price WTI Brent OPEC energy crude',
    'AI_반도체': 'AI semiconductor chip Nvidia technology spending',
    '한국_원화': 'Korean won USDKRW Korea stock market',
    '유럽_ECB': 'ECB European Central Bank euro interest rate',
    '부동산': 'real estate REIT housing property',
    '저출산_인구': 'demographics birth rate aging population',
    '비트코인_크립토': 'bitcoin crypto digital currency',
    '금': 'gold price precious metals safe haven',
}


def _get_vectordb():
    """뉴스 벡터DB 모듈 lazy import"""
    try:
        from market_research import news_vectordb
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'news_vectordb', BASE_DIR / 'news_vectordb.py')
        news_vectordb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(news_vectordb)
    return news_vectordb


def _search_corroborating(vectordb, month_str: str, topic: str,
                          claims: list[str], top_k: int = 3) -> list[dict]:
    """토픽의 claim들을 조합한 쿼리로 뉴스 검색 → 뒷받침 뉴스 반환"""
    # 영문 토픽 쿼리 + claim에서 핵심 키워드 추출
    base_query = TOPIC_QUERY_MAP.get(topic, topic)

    # claim 텍스트에서 숫자/영문 키워드 추출하여 쿼리 보강
    claim_keywords = []
    for c in claims[:3]:
        # 영문 단어 추출
        words = [w for w in c.split() if w.isascii() and len(w) > 2]
        claim_keywords.extend(words[:3])

    query = f"{base_query} {' '.join(claim_keywords[:5])}"

    try:
        results = vectordb.search(query, month_str, top_k=top_k * 2)
    except Exception:
        return []

    # 중복 제거 + 상위 top_k
    seen = set()
    deduped = []
    for r in results:
        prefix = r.get('title', '')[:40]
        if prefix in seen:
            continue
        seen.add(prefix)
        deduped.append({
            'title': r.get('title', ''),
            'date': r.get('date', ''),
            'source': r.get('source', ''),
            'distance': r.get('distance', 1.0),
            'url': r.get('url', ''),
        })
        if len(deduped) >= top_k:
            break

    return deduped


def build_enriched_digest(year: int, month: int) -> dict:
    """월별 digest를 뉴스로 교차검증한 enriched digest 생성"""
    month_str = f'{year}-{month:02d}'
    digest_path = DIGEST_DIR / f'{month_str}.json'

    if not digest_path.exists():
        print(f'  digest 없음: {digest_path}')
        return {}

    digest = json.loads(digest_path.read_text(encoding='utf-8'))
    vectordb = _get_vectordb()

    enriched_topics = {}
    total_news = 0

    for topic, info in digest.get('topics', {}).items():
        claims = info.get('key_claims', [])
        events = info.get('key_events', [])
        search_texts = (claims + events)[:5]  # 최대 5개로 제한

        if not search_texts:
            enriched_topics[topic] = {**info, 'corroborating_news': []}
            continue

        news = _search_corroborating(vectordb, month_str, topic, search_texts)
        total_news += len(news)

        # 평균 유사도 (distance가 낮을수록 유사)
        avg_dist = (sum(n['distance'] for n in news) / len(news)) if news else 1.0

        enriched_topics[topic] = {
            **info,
            'corroborating_news': news,
            'corroboration_score': round(1.0 - avg_dist, 3),  # 0~1, 높을수록 강함
        }

    enriched = {
        **digest,
        'topics': enriched_topics,
        'enriched': True,
        'total_corroborating_news': total_news,
    }

    # 저장
    ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ENRICHED_DIR / f'{month_str}.json'
    out_path.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    print(f'  enriched digest: {month_str} — {len(enriched_topics)} topics, '
          f'{total_news} corroborating news')

    return enriched


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        y, m = int(sys.argv[1]), int(sys.argv[2])
    else:
        from datetime import datetime
        now = datetime.now()
        y, m = now.year, now.month
    build_enriched_digest(y, m)
