# -*- coding: utf-8 -*-
"""
뉴스 salience 이중 점수: event_salience + asset_relevance

- event_salience: "이 사건이 시장에 얼마나 중요한가"
- asset_relevance: "이 기사가 특정 자산군에 얼마나 직결되는가"
"""

from market_research.analyze.news_classifier import TOPIC_ASSET_SENSITIVITY

# 신뢰 소스
TRUSTED_SOURCES = {
    'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ',
    'CNBC', 'Yonhap', '연합뉴스', 'SeekingAlpha', 'Benzinga',
    'The Times of India', 'MarketWatch',
}

# 거시 키워드 (uncategorized fallback 판정용)
MACRO_KEYWORDS = [
    'Fed', 'FOMC', '연준', 'ECB', 'BOJ', 'BOK', '금통위',
    'CPI', 'GDP', '고용', '실업', '금리', 'rate', 'inflation',
    '관세', 'tariff', '무역', 'trade war',
    'recession', '침체', 'stagflation',
    'S&P', 'KOSPI', '증시', 'stock market',
    'crude', 'oil', '유가', 'gold', '금값',
    '원달러', 'USD', 'KRW', '환율',
]


def compute_event_salience(article: dict, bm_anomaly_dates: set = None) -> float:
    """사건 중요도 점수 (0~1).

    Parameters
    ----------
    article : dict — 분류 완료된 뉴스 기사
    bm_anomaly_dates : set — BM z>1.5인 날짜 집합 (YYYY-MM-DD)
    """
    if bm_anomaly_dates is None:
        bm_anomaly_dates = set()

    # source quality
    source = article.get('source', '')
    source_quality = 1.0 if source in TRUSTED_SOURCES else 0.3

    # intensity (0~1)
    intensity_norm = min(article.get('intensity', 0) / 10.0, 1.0)

    # corroboration (event_group source count)
    source_count = article.get('_event_source_count', 1)
    corroboration = min(source_count / 5.0, 1.0)

    # BM move overlap
    art_date = article.get('date', '')[:10]
    bm_overlap = 1.0 if art_date in bm_anomaly_dates else 0.0

    score = (0.30 * source_quality
             + 0.25 * intensity_norm
             + 0.25 * corroboration
             + 0.20 * bm_overlap)

    return round(score, 3)


def compute_asset_relevance(article: dict) -> dict:
    """자산군별 관련도 점수 (13키).

    TOPIC_ASSET_SENSITIVITY 룩업 기반.
    """
    topics = article.get('_classified_topics', [])
    if not topics:
        return {}

    relevance = {}
    for t in topics:
        topic_name = t.get('topic', '')
        intensity = t.get('intensity', 5) / 10.0
        sensitivity = TOPIC_ASSET_SENSITIVITY.get(topic_name, {})
        for asset_key, base_val in sensitivity.items():
            score = abs(base_val) * intensity
            relevance[asset_key] = max(relevance.get(asset_key, 0), score)

    return {k: round(v, 3) for k, v in relevance.items() if v >= 0.1}


def compute_salience(article: dict, bm_anomaly_dates: set = None) -> dict:
    """통합: event_salience + asset_relevance 계산 후 기사에 필드 추가."""
    article['_event_salience'] = compute_event_salience(article, bm_anomaly_dates)
    article['_asset_relevance'] = compute_asset_relevance(article)
    return article


def compute_salience_batch(articles: list[dict], bm_anomaly_dates: set = None) -> list[dict]:
    """배치 salience 계산."""
    for a in articles:
        compute_salience(a, bm_anomaly_dates)
    return articles


def title_keyword_score(article: dict) -> float:
    """제목 내 거시 키워드 강도 (0~1). uncategorized fallback용."""
    title = article.get('title', '').lower()
    matches = sum(1 for kw in MACRO_KEYWORDS if kw.lower() in title)
    return min(matches / 3.0, 1.0)


def is_market_relevant(article: dict, bm_anomaly_dates: set = None) -> bool:
    """미분류 기사의 시장 relevance 판정. 최소 2개 조건 충족."""
    if bm_anomaly_dates is None:
        bm_anomaly_dates = set()

    conditions = [
        article.get('source', '') in TRUSTED_SOURCES,
        article.get('date', '')[:10] in bm_anomaly_dates,
        any(kw.lower() in article.get('title', '').lower() for kw in MACRO_KEYWORDS),
        article.get('_event_source_count', 0) >= 2,
        title_keyword_score(article) >= 0.5,
    ]
    return sum(conditions) >= 2
