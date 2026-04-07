# -*- coding: utf-8 -*-
"""벤치마크 매핑 — SCIP dataset/dataseries + 뉴스 검색용 자산군/키워드"""

# ── 32개 BM → SCIP 매핑 ──
BENCHMARK_MAP = {
    # 주식
    '글로벌주식':    {'dataset_id': 35,  'ds_id': 39, 'category': '주식'},
    'KOSPI':       {'dataset_id': 253, 'ds_id': 9,  'category': '주식'},
    'KOSPI_PRICE': {'dataset_id': 253, 'ds_id': 15, 'category': '주식', 'blob_key': 'KRW'},
    'KOSPI200':    {'dataset_id': 225, 'ds_id': 9,  'category': '주식'},
    'S&P500':      {'dataset_id': 271, 'ds_id': 6,  'category': '주식'},
    '미국성장주':    {'dataset_id': 237, 'ds_id': 6,  'category': '주식'},
    '미국가치주':    {'dataset_id': 238, 'ds_id': 6,  'category': '주식'},
    'Russell2000': {'dataset_id': 338, 'ds_id': 9,  'category': '주식'},
    '고배당':       {'dataset_id': 275, 'ds_id': 9,  'category': '주식'},
    '미국외선진국':  {'dataset_id': 339, 'ds_id': 9,  'category': '주식'},
    '신흥국주식':    {'dataset_id': 340, 'ds_id': 9,  'category': '주식'},
    # 채권
    '글로벌채권UH': {'dataset_id': 58,  'ds_id': 39, 'category': '채권'},
    '글로벌채권H':  {'dataset_id': 58,  'ds_id': 44, 'category': '채권'},
    '글로벌채권HKRW': {'dataset_id': 256, 'ds_id': 9, 'category': '채권'},
    '매경채권국채3년': {'dataset_id': 422, 'ds_id': 9, 'category': '채권'},
    'KRX10년채권':  {'dataset_id': 421, 'ds_id': 9,  'category': '채권'},
    'KAP종합채권':  {'dataset_id': 257, 'ds_id': 9,  'category': '채권'},
    '미국종합채권':  {'dataset_id': 278, 'ds_id': 6,  'category': '채권'},
    '미국IG':      {'dataset_id': 233, 'ds_id': 6,  'category': '채권'},
    '미국HY':      {'dataset_id': 234, 'ds_id': 6,  'category': '채권'},
    '신흥국채권':    {'dataset_id': 244, 'ds_id': 9,  'category': '채권'},
    # 대체
    'Gold':        {'dataset_id': 408, 'ds_id': 48, 'category': '대체'},
    'WTI':         {'dataset_id': 98,  'ds_id': 15, 'category': '대체'},
    '미국리츠':     {'dataset_id': 317, 'ds_id': 6,  'category': '대체'},
    '원자재종합':    {'dataset_id': 235, 'ds_id': 9,  'category': '대체'},
    # 통화
    'DXY':         {'dataset_id': 105, 'ds_id': 6,  'category': '통화'},
    'EMCI':        {'dataset_id': 419, 'ds_id': 48, 'category': '통화'},
    'EURUSD':      {'dataset_id': 359, 'ds_id': 48, 'category': '통화'},
    'JPYUSD':      {'dataset_id': 365, 'ds_id': 48, 'category': '통화'},
    'GBPUSD':      {'dataset_id': 360, 'ds_id': 48, 'category': '통화'},
    'CADUSD':      {'dataset_id': 372, 'ds_id': 48, 'category': '통화'},
    'AUDUSD':      {'dataset_id': 371, 'ds_id': 48, 'category': '통화'},
    'USDKRW':      {'dataset_id': 31,  'ds_id': 6,  'category': '통화'},
}

# ── BM → 뉴스 검색용 자산군 ──
BM_ASSET_CLASS_MAP = {
    'S&P500': '해외주식', '미국성장주': '해외주식', '미국가치주': '해외주식',
    'Russell2000': '해외주식', '고배당': '해외주식',
    'KOSPI': '국내주식', 'KOSPI200': '국내주식',
    '미국외선진국': '해외주식', '신흥국주식': '해외주식', '글로벌주식': '해외주식',
    '미국종합채권': '해외채권', '미국IG': '해외채권', '미국HY': '해외채권',
    '신흥국채권': '해외채권', '글로벌채권UH': '해외채권',
    'KAP종합채권': '국내채권', '매경채권국채3년': '국내채권', 'KRX10년채권': '국내채권',
    'Gold': '대체투자', 'WTI': '대체투자', '미국리츠': '대체투자', '원자재종합': '대체투자',
    'DXY': '통화', 'USDKRW': '통화', 'EMCI': '통화',
}

# ── BM → 뉴스 검색 키워드 ──
BM_SEARCH_QUERIES = {
    'S&P500': 'S&P 500 US stock market',
    'KOSPI': 'KOSPI Korea stock market 코스피',
    'Gold': 'gold price precious metals 금 가격',
    'DXY': 'US dollar index DXY strength weakness',
    'USDKRW': 'USD KRW Korean won exchange rate 원달러 환율',
    '미국종합채권': 'US bond Treasury yield interest rate',
    '미국성장주': 'US growth stocks technology Nasdaq',
    '미국가치주': 'US value stocks dividend',
    '미국외선진국': 'developed markets EAFE Europe Japan',
    '신흥국주식': 'emerging markets EM stocks',
    'WTI': 'oil price WTI crude 유가',
    '미국HY': 'high yield bonds credit spreads',
}
