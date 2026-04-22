# -*- coding: utf-8 -*-
"""
뉴스 salience 이중 점수: event_salience + asset_relevance

- event_salience: "이 사건이 시장에 얼마나 중요한가"
- asset_relevance: "이 기사가 특정 자산군에 얼마나 직결되는가"
"""

from market_research.analyze.news_classifier import TOPIC_ASSET_SENSITIVITY


# ═══════════════════════════════════════════════════════
# BM Anomaly Dates — z>1.5 날짜 추출
# ═══════════════════════════════════════════════════════

def load_bm_anomaly_dates(year: int, month: int, threshold_z: float = 1.5) -> set:
    """SCIP BM 시계열에서 z-score > threshold인 날짜 집합 추출.

    핵심 6개 BM(S&P500, KOSPI, Gold, DXY, USDKRW, 미국종합채권)의
    5일 수익률 / 20일 vol로 z-score 계산, 어느 BM이든 초과 시 해당 날짜 포함.
    """
    try:
        from market_research.core.db import get_conn, parse_blob
        from market_research.core.benchmarks import BENCHMARK_MAP
    except ImportError:
        return set()

    core_bms = ['S&P500', 'KOSPI', 'Gold', 'DXY', 'USDKRW', '미국종합채권']
    configs = {n: BENCHMARK_MAP[n] for n in core_bms if n in BENCHMARK_MAP}
    if not configs:
        return set()

    # 3개월 lookback (vol 계산 안정성)
    from datetime import date as _date
    end_dt = _date(year, month, 28)  # 월말 근사
    start_dt = _date(year, month, 1) - __import__('datetime').timedelta(days=90)
    start_int = int(start_dt.strftime('%Y%m%d'))
    end_int = int(end_dt.strftime('%Y%m%d'))

    ds_ids = list(set(c['dataset_id'] for c in configs.values()))
    dser_ids = list(set(c['ds_id'] for c in configs.values()))

    try:
        conn = get_conn('SCIP')
        cur = conn.cursor()
        placeholders_ds = ','.join(['%s'] * len(ds_ids))
        placeholders_dser = ','.join(['%s'] * len(dser_ids))
        cur.execute(
            f"""SELECT dataset_id, dataseries_id,
                       DATE(timestamp_observation) AS dt, data
                FROM back_datapoint
                WHERE dataset_id IN ({placeholders_ds})
                  AND dataseries_id IN ({placeholders_dser})
                  AND timestamp_observation >= %s
                  AND timestamp_observation <= %s
                ORDER BY dataset_id, timestamp_observation""",
            ds_ids + dser_ids + [start_dt.isoformat(), end_dt.isoformat()])
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return set()

    if not rows:
        return set()

    # BM별 시계열 구축 + z-score 계산
    import pandas as pd
    date_max_z = {}  # date → max z-score across all BMs
    month_str = f'{year}-{month:02d}'

    for bm_name, cfg in configs.items():
        ds_id, dser_id = cfg['dataset_id'], cfg['ds_id']
        blob_key = cfg.get('blob_key')
        prices = []
        for r in rows:
            if r['dataset_id'] == ds_id and r['dataseries_id'] == dser_id:
                try:
                    val = parse_blob(r['data'], blob_key)
                    if val is not None and val > 0:
                        prices.append({'date': str(r['dt']), 'price': float(val)})
                except Exception:
                    pass
        if len(prices) < 30:
            continue

        df = pd.DataFrame(prices).drop_duplicates('date').sort_values('date')
        df['ret'] = df['price'].pct_change()
        df['ret_5d'] = df['price'].pct_change(5)
        df['vol_20d'] = df['ret'].rolling(20).std()
        df['z'] = df['ret_5d'].abs() / df['vol_20d']

        # 해당 월의 z > threshold 날짜 수집 (z값도 보존)
        mask = df['date'].str.startswith(month_str) & (df['z'] > threshold_z)
        for _, row_data in df[mask].iterrows():
            d = row_data['date'][:10]
            date_max_z[d] = max(date_max_z.get(d, 0), row_data['z'])

    # 상위 7일 캡 (고변동 월에서 signal 희석 방지)
    MAX_ANOMALY_DAYS = 7
    if len(date_max_z) > MAX_ANOMALY_DAYS:
        top_dates = sorted(date_max_z.keys(), key=lambda d: -date_max_z[d])[:MAX_ANOMALY_DAYS]
        return set(top_dates)

    return set(date_max_z.keys())

# 소스 품질 3단계 (1.0 / 0.7 / 0.3)
# Tier 1: 글로벌 통신사 + 전문 매체
TIER1_SOURCES = {
    'Reuters', 'Bloomberg', 'AP', 'Financial Times', 'WSJ',
    'CNBC', 'MarketWatch',
    # 국내 통신사
    'Yonhap', '연합뉴스', '연합뉴스TV', '뉴시스', '뉴스1',
}
# Tier 2: 주요 경제지 + 준전문 매체
TIER2_SOURCES = {
    # 글로벌
    'SeekingAlpha', 'Benzinga', 'The Times of India', 'Business Insider',
    'Forbes', 'Fortune', 'NPR', 'BBC News', 'CoinDesk',
    # 국내 경제지
    '매일경제', '한국경제', '서울경제', '머니투데이', '이데일리',
    '파이낸셜뉴스', '아시아경제', '헤럴드경제', '더벨', '비즈니스포스트',
    # 국내 종합일간지
    '조선일보', '조선비즈', '동아일보', '중앙일보', '한겨레',
    # 네이버 포탈 (실제 언론사명 미파싱된 경우)
    '네이버금융',
}
# Tier 3: 나머지 (0.3)
# 네이버검색(미파싱), 블로그, 알 수 없는 소스

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

    # source quality (3단계: 1.0 / 0.7 / 0.3)
    # Phase 2.5 (2026-04-22): source_type='naver_research'면 adapter가 산출한
    # _research_quality_score를 source_quality 슬롯으로 사용. 가중치 합은 그대로.
    if article.get('source_type') == 'naver_research':
        rqs = article.get('_research_quality_score')
        source_quality = float(rqs) if rqs is not None else 0.7  # adapter 미실행 fallback
    else:
        source = article.get('source', '')
        if source in TIER1_SOURCES:
            source_quality = 1.0
        elif source in TIER2_SOURCES:
            source_quality = 0.7
        else:
            source_quality = 0.3

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
    """배치 salience 계산. bm_anomaly_dates가 제공되면 20% 가중치 활성화."""
    if bm_anomaly_dates:
        print(f'  salience: bm_anomaly {len(bm_anomaly_dates)}일 연동')
    for a in articles:
        compute_salience(a, bm_anomaly_dates)
    return articles


def title_keyword_score(article: dict) -> float:
    """제목 내 거시 키워드 강도 (0~1). uncategorized fallback용."""
    title = article.get('title', '').lower()
    matches = sum(1 for kw in MACRO_KEYWORDS if kw.lower() in title)
    return min(matches / 3.0, 1.0)


def is_market_relevant(article: dict, bm_anomaly_dates: set = None) -> bool:
    """미분류 기사의 시장 relevance 판정.

    키워드 조건(3 or 5) 필수 + 나머지 1개 이상 충족.
    키워드 필수로 Netflix/학자금/사이버 같은 비금융 기사 차단.
    """
    if bm_anomaly_dates is None:
        bm_anomaly_dates = set()

    title_lower = article.get('title', '').lower()
    has_keyword = any(kw.lower() in title_lower for kw in MACRO_KEYWORDS)
    kw_score = title_keyword_score(article)

    # 키워드 조건 필수 (둘 중 하나)
    if not has_keyword and kw_score < 0.5:
        return False

    source = article.get('source', '')
    other_conditions = [
        source in TIER1_SOURCES or source in TIER2_SOURCES,
        article.get('date', '')[:10] in bm_anomaly_dates,
        article.get('_event_source_count', 0) >= 2,
    ]
    return sum(other_conditions) >= 1


# ═══════════════════════════════════════════════════════
# Uncategorized Fallback — 미분류 기사 구제
# ═══════════════════════════════════════════════════════

# 키워드 → 토픽 매핑 (제목에서 매칭)
# V2 Taxonomy 기준 키워드→토픽 매핑
_KEYWORD_TOPIC_MAP = {
    # 통화정책
    'fed': '통화정책', 'fomc': '통화정책', '연준': '통화정책', 'ecb': '통화정책',
    'boj': '통화정책', 'bok': '통화정책', '금통위': '통화정책',
    'rate hike': '통화정책', 'rate cut': '통화정책',
    # 금리/채권
    '금리': '금리_채권', 'interest rate': '금리_채권', '국채': '금리_채권',
    'yield': '금리_채권', 'treasury': '금리_채권', 'bond': '금리_채권',
    # 물가
    'cpi': '물가_인플레이션', 'inflation': '물가_인플레이션', '물가': '물가_인플레이션',
    'pce': '물가_인플레이션',
    # 경기/소비
    'gdp': '경기_소비', '고용': '경기_소비', '실업': '경기_소비',
    'recession': '경기_소비', '침체': '경기_소비', 'nonfarm': '경기_소비',
    'payroll': '경기_소비', 'job': '경기_소비', '소비자심리': '경기_소비',
    # 관세/무역
    '관세': '관세_무역', 'tariff': '관세_무역', '무역': '관세_무역',
    'trade war': '관세_무역',
    # 에너지/원자재
    'crude': '에너지_원자재', 'oil': '에너지_원자재', '유가': '에너지_원자재',
    'opec': '에너지_원자재',
    # 귀금속/금
    'gold': '귀금속_금', '금값': '귀금속_금', '금 가격': '귀금속_금',
    # 환율
    '원달러': '환율_FX', '환율': '환율_FX', 'usdkrw': '환율_FX', 'dollar': '환율_FX',
    # 지정학
    'war': '지정학', '전쟁': '지정학', 'sanction': '지정학', '제재': '지정학',
    # 테크
    'ai ': '테크_AI_반도체', '반도체': '테크_AI_반도체',
    'semiconductor': '테크_AI_반도체', 'nvidia': '테크_AI_반도체',
    # 크립토
    'bitcoin': '크립토', '비트코인': '크립토',
}


def fallback_classify_uncategorized(articles: list[dict],
                                     bm_anomaly_dates: set = None) -> int:
    """미분류 기사(_classified_topics==[] 또는 미존재) 중 시장 관련 기사에 fallback 분류 부여.

    Returns: fallback 분류된 기사 수
    """
    count = 0
    for a in articles:
        topics = a.get('_classified_topics')
        # 이미 분류된 기사 스킵
        if topics:
            continue
        # 분류 에러 기사도 스킵 (재시도 대상)
        if '_classify_error' in a:
            continue
        # Financial Filter 탈락 기사 스킵 (filter 결과를 되살리지 않음)
        if a.get('_filter_reason'):
            continue

        if not is_market_relevant(a, bm_anomaly_dates):
            continue

        # 키워드 매칭으로 토픽 결정
        title_lower = a.get('title', '').lower()
        matched_topics = {}
        for keyword, topic in _KEYWORD_TOPIC_MAP.items():
            if keyword in title_lower:
                matched_topics[topic] = max(matched_topics.get(topic, 0), 4)  # base intensity 4

        if not matched_topics:
            # 키워드 없어도 relevant → 범용 '경기_소비' 토픽 (V2)
            matched_topics = {'경기_소비': 3}

        # fallback 분류 결과 부여
        fallback_topics = []
        for topic, intensity in sorted(matched_topics.items(), key=lambda x: -x[1]):
            fallback_topics.append({
                'topic': topic,
                'direction': 'neutral',
                'intensity': intensity,
            })

        a['_classified_topics'] = fallback_topics
        a['_fallback_classified'] = True
        a['primary_topic'] = fallback_topics[0]['topic']
        a['direction'] = 'neutral'
        a['intensity'] = fallback_topics[0]['intensity']

        # asset impact vector (TOPIC_ASSET_SENSITIVITY 룩업)
        impact = {}
        for t in fallback_topics:
            sensitivity = TOPIC_ASSET_SENSITIVITY.get(t['topic'], {})
            scale = t['intensity'] / 10.0
            for asset_key, base_val in sensitivity.items():
                score = abs(base_val) * scale
                impact[asset_key] = max(impact.get(asset_key, 0), score)
        a['_asset_impact_vector'] = {k: round(v, 2) for k, v in impact.items() if v >= 0.3}

        count += 1

    return count
