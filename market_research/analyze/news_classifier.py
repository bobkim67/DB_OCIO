# -*- coding: utf-8 -*-
"""
뉴스 분류기 — 21개 주제 계층형 태깅 + 자산 영향도 벡터
=======================================================
2단계 분류:
  Step 1: 주제(Topic) 태깅 — 21개 주제 multi-label, 방향성+강도
  Step 2: 자산별 영향도 벡터(Asset Impact Vector) — [국내주식,국내채권,해외주식,해외채권]

미분류 잔류 기사 → '신규 내러티브 후보' 키워드 추출 → narrative_candidates.json

사용법:
    python -m market_research.news_classifier 2026-03
    python -m market_research.news_classifier              # 최신 월
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from market_research.core.json_utils import (
    safe_read_json_list, safe_write_json_list, safe_write_news_json,
)

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
NEWS_DIR = BASE_DIR / 'data' / 'news'
CANDIDATES_FILE = BASE_DIR / 'data' / 'narrative_candidates.json'

# ═══════════════════════════════════════════════════════
# 21개 주제 분류 체계
# ═══════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════
# Taxonomy V2 (14개) — 2026-04-09 개편
# ═══════════════════════════════════════════════════════

TOPIC_TAXONOMY = [
    '통화정책',          # Fed/ECB/BOJ/BOK 정책결정, 점도표, 기준금리
    '금리_채권',         # 국채 금리, 채권 수익률, 크레딧 스프레드, 국채 입찰
    '물가_인플레이션',    # CPI, PPI, PCE, 기대 인플레, 임금상승
    '경기_소비',         # GDP, 고용, 실업, 소비자심리, PMI, 소매판매, 경기침체
    '유동성_크레딧',     # 레포, 크로스커런시 베이시스, TGA, SRF, 회사채 발행환경, CP/CD
    '환율_FX',          # 원달러, 엔달러, 위안, DXY, FX 개입
    '달러_글로벌유동성',  # 유로달러 시스템, 달러 부족/과잉, Fed 스왑라인
    '에너지_원자재',     # 유가, WTI, Brent, OPEC, 천연가스, 원자재 지수
    '귀금속_금',         # 금값, 은값, 안전자산 수요 (금 중심)
    '지정학',            # 전쟁의 시장 영향, 제재의 경제 효과, 호르무즈 봉쇄
    '부동산',            # 주택가격, 전세, 리츠, 건설경기, 부동산 정책
    '관세_무역',         # 관세율, 무역수지, 공급망 재편
    '크립토',            # 비트코인, 이더리움, 스테이블코인, DeFi
    '테크_AI_반도체',    # AI 투자, 반도체 수급, 빅테크 실적의 시장 영향
]

# ── Old → New 매핑 (기존 21개 → 14개) ──
OLD_TO_NEW_TOPIC = {
    '금리': '금리_채권', '미국채': '금리_채권',
    '물가': '물가_인플레이션',
    '관세': '관세_무역',
    '유가_에너지': '에너지_원자재',
    '금': '귀금속_금', '안전자산': '귀금속_금',
    '비트코인_크립토': '크립토',
    'AI_반도체': '테크_AI_반도체', 'AI_반도': '테크_AI_반도체',
    '한국_원화': '환율_FX', '중국_위안화': '환율_FX', '엔화_캐리': '환율_FX',
    '유럽_ECB': '통화정책',
    '유로달러': '달러_글로벌유동성', '달러': '환율_FX',
    '유동성_배관': '유동성_크레딧',
    '이민_노동': '경기_소비', '저출산_인구': '경기_소비',
    # 유지
    '통화정책': '통화정책', '지정학': '지정학', '부동산': '부동산',
    # fallback 토픽
    '거시경제': '경기_소비', '경기': '경기_소비', '미국증시': '테크_AI_반도체',
    '한국증시': '환율_FX', '유가': '에너지_원자재', '환율': '환율_FX', '기술': '테크_AI_반도체',
}

def migrate_topic(old_topic: str) -> str:
    """기존 토픽 → 신규 토픽 변환. 매핑 없으면 원본 반환."""
    return OLD_TO_NEW_TOPIC.get(old_topic, old_topic)


# ═══════════════════════════════════════════════════════
# Financial Filter (Layer 1) — 분류 전 앞단
# ═══════════════════════════════════════════════════════

# 개별종목/상품 패턴 (우선 차단)
_STOCK_PATTERNS = [
    '주총', '상장 효과', 'ipo 효과', '공모 금액', '수주', '분기 실적',
    '영업이익 증가', '영업이익 감소', '대표이사 선임', '인수합병',
    '시가총액 돌파', '목표가 상향', '목표가 하향', '주가 강세', '주가 약세',
    '배당금 지급', '자사주 매입', '신규 상장',
]
_PRODUCT_PATTERNS = [
    '펀드 출시', '펀드 선봬', '펀드 선보', 'etf 소개', 'etf 출시',
    '자산운용 출시', '상품 출시', '분배금 공개', '분배금 계획',
    '운용보수', '환매 수수료', '수익률 기록', '브리핑',
]
_INDUSTRY_PATTERNS = [
    '시장점유율', '공장 건설', '공장 재건축', '생산라인', '신제품 출시',
    '출하량 증가', '수주잔고',
]
# 거시 파급 키워드 (이게 있으면 개별종목이라도 거시 맥락)
_MACRO_OVERRIDE = [
    '시장 전체', '증시 급락', '증시 급등', '시장 충격', '시스템 리스크',
    '금융위기', '통화정책 영향', '경기 침체', '인플레이션 우려',
    'market crash', 'financial crisis', 'systemic risk', 'global markets',
    'market turmoil', 'market rout', 'market rally',
]


def is_macro_financial(article: dict) -> tuple:
    """거시 금융 관련성 판정. (True, '') 또는 (False, filter_reason).

    우선순위: 개별종목/상품/산업 패턴 먼저 차단 → 거시 macro 체크.
    """
    title = article.get('title', '').lower()
    desc = article.get('description', '')[:200].lower()
    text = f"{title} {desc}"

    # 거시 파급 명시 → 무조건 통과
    if any(kw in text for kw in _MACRO_OVERRIDE):
        return (True, '')

    # 개별종목 패턴 우선 차단
    if any(p in text for p in _STOCK_PATTERNS):
        return (False, 'individual_stock')

    # 상품/운용사 패턴
    if any(p in text for p in _PRODUCT_PATTERNS):
        return (False, 'product_promo')

    # 산업/섹터 패턴
    if any(p in text for p in _INDUSTRY_PATTERNS):
        return (False, 'industry_sector')

    # 순수 군사 (금융 키워드 없음)
    MILITARY_KW = {'지상전', '공습', '미사일', '폭격', '병력', '작전', '침공'}
    FINANCIAL_KW = {'가격', '시장', '경제', '투자', '주가', '환율', '유가', '채권',
                    'price', 'market', 'economy', 'oil', 'crude', 'bond', 'stock',
                    'yield', 'treasury', 'equity', 'currency', 'fx', 'lng', 'opec',
                    'petrodollar', 'investor', 'trade', 'tariff'}
    if any(kw in text for kw in MILITARY_KW) and not any(kw in text for kw in FINANCIAL_KW):
        return (False, 'pure_military')

    # 순수 정치
    POLITICS_KW = {'여론조사', '지지율', '선거 결과', '정당 대표', '국회 본회의', 'polls'}
    if any(kw in text for kw in POLITICS_KW) and not any(kw in text for kw in FINANCIAL_KW):
        return (False, 'pure_politics')

    # 금융 키워드 체크
    MACRO_KW = {'금리', '환율', '증시', '채권', '유가', '인플레', 'gdp', '고용', '실업',
                'cpi', 'fed', 'ecb', 'fomc', 'kospi', 's&p', '나스닥', '원달러',
                'rate', 'yield', 'yields', 'bond', 'bonds', 'stock market', 'stocks',
                'oil price', 'oil prices', 'crude', 'inflation', 'recession',
                'tariff', 'tariffs', 'trade', '관세', '무역', '금값', '비트코인', '경기',
                'markets', 'treasury', 'treasuries', 'equity', 'equities',
                'investor', 'investors', 'currency', 'currencies', 'fx',
                'lng', 'opec', 'petrodollar', 'commodity', 'commodities',
                'energy crisis', 'economic', 'economy', 'financial',
                '부동산', '리츠', 'reit', 'reits', 'real estate'}
    if not any(kw in text for kw in MACRO_KW):
        # source-aware: Tier1 금융 전문 매체는 title만으로 통과 허용
        source = article.get('source', '')
        FINANCIAL_SOURCES = {'Reuters', 'Bloomberg', 'CNBC', 'MarketWatch',
                             'Financial Times', 'WSJ', 'SeekingAlpha', 'Benzinga'}
        if source in FINANCIAL_SOURCES:
            return (True, '')
        return (False, 'non_financial')

    return (True, '')

# 주제 → 자산군 기본 영향 매핑 (analysis_worldview.json + TOPIC_TO_ASSETS 기반)
# 4대 자산군 + 9개 세부 자산 = 13키
# 값: 기본 민감도 방향 (+1=동행, -1=역행, 0=약함)
#
# 세부 자산:
#   해외채권_USHY, 해외채권_USIG, 해외채권_EM
#   미국주식_성장, 미국주식_가치
#   원자재_금, 원자재_원유
#   환율_USDKRW, 환율_DXY
ASSET_KEYS = [
    '국내주식', '국내채권', '해외주식', '해외채권',
    '해외채권_USHY', '해외채권_USIG', '해외채권_EM',
    '미국주식_성장', '미국주식_가치',
    '원자재_금', '원자재_원유',
    '환율_USDKRW', '환율_DXY',
]

# V2 Taxonomy (14개 토픽) 기준 — 기존 V1 값을 병합
TOPIC_ASSET_SENSITIVITY = {
    '통화정책':         {'국내주식': -0.4, '국내채권': -0.6, '해외주식': -0.5, '해외채권': -0.7,
                         '해외채권_USHY': -0.5, '해외채권_USIG': -0.8, '해외채권_EM': -0.6,
                         '미국주식_성장': -0.7, '미국주식_가치': -0.3,
                         '원자재_금': 0.3, '원자재_원유': -0.2,
                         '환율_USDKRW': -0.4, '환율_DXY': 0.5},
    '금리_채권':        {'국내주식': -0.3, '국내채권': -0.8, '해외주식': -0.5, '해외채권': -0.9,
                         '해외채권_USHY': -0.7, '해외채권_USIG': -0.9, '해외채권_EM': -0.6,
                         '미국주식_성장': -0.7, '미국주식_가치': -0.3,
                         '원자재_금': 0.3, '원자재_원유': -0.2,
                         '환율_USDKRW': -0.4, '환율_DXY': 0.5},
    '물가_인플레이션':   {'국내주식': -0.3, '국내채권': -0.5, '해외주식': -0.4, '해외채권': -0.6,
                         '해외채권_USHY': -0.4, '해외채권_USIG': -0.7, '해외채권_EM': -0.5,
                         '미국주식_성장': -0.6, '미국주식_가치': -0.2,
                         '원자재_금': 0.4, '원자재_원유': 0.3,
                         '환율_USDKRW': -0.3, '환율_DXY': 0.3},
    '경기_소비':        {'국내주식': -0.4, '국내채권': -0.1, '해외주식': -0.3, '해외채권': 0.1,
                         '해외채권_USHY': -0.2, '해외채권_USIG': 0.1, '해외채권_EM': -0.2,
                         '미국주식_성장': -0.4, '미국주식_가치': -0.2,
                         '원자재_금': 0.1, '원자재_원유': -0.3,
                         '환율_USDKRW': -0.2, '환율_DXY': 0.1},
    '유동성_크레딧':     {'국내주식': -0.3, '국내채권': -0.4, '해외주식': -0.4, '해외채권': -0.5,
                         '해외채권_USHY': -0.7, '해외채권_USIG': -0.3, '해외채권_EM': -0.8,
                         '미국주식_성장': -0.5, '미국주식_가치': -0.3,
                         '원자재_금': 0.2, '원자재_원유': -0.3,
                         '환율_USDKRW': -0.5, '환율_DXY': 0.6},
    '환율_FX':          {'국내주식': -0.5, '국내채권': -0.1, '해외주식': -0.3, '해외채권': -0.1,
                         '해외채권_USHY': -0.1, '해외채권_USIG': 0.0, '해외채권_EM': -0.5,
                         '미국주식_성장': -0.2, '미국주식_가치': -0.1,
                         '원자재_금': -0.2, '원자재_원유': -0.2,
                         '환율_USDKRW': -0.8, '환율_DXY': 0.5},
    '달러_글로벌유동성': {'국내주식': -0.4, '국내채권': -0.2, '해외주식': -0.4, '해외채권': -0.4,
                         '해외채권_USHY': -0.3, '해외채권_USIG': -0.2, '해외채권_EM': -0.6,
                         '미국주식_성장': -0.3, '미국주식_가치': -0.2,
                         '원자재_금': -0.1, '원자재_원유': -0.3,
                         '환율_USDKRW': -0.7, '환율_DXY': 0.8},
    '에너지_원자재':     {'국내주식': -0.3, '국내채권': -0.2, '해외주식': -0.3, '해외채권': -0.3,
                         '해외채권_USHY': -0.4, '해외채권_USIG': -0.1, '해외채권_EM': -0.3,
                         '미국주식_성장': -0.3, '미국주식_가치': 0.2,
                         '원자재_금': 0.1, '원자재_원유': 0.9,
                         '환율_USDKRW': -0.2, '환율_DXY': 0.1},
    '귀금속_금':        {'국내주식': -0.2, '국내채권': 0.2,  '해외주식': -0.3, '해외채권': 0.3,
                         '해외채권_USHY': -0.1, '해외채권_USIG': 0.4, '해외채권_EM': -0.2,
                         '미국주식_성장': -0.5, '미국주식_가치': -0.1,
                         '원자재_금': 0.9, '원자재_원유': -0.1,
                         '환율_USDKRW': -0.2, '환율_DXY': -0.4},
    '지정학':           {'국내주식': -0.5, '국내채권': 0.2,  '해외주식': -0.6, '해외채권': 0.3,
                         '해외채권_USHY': -0.5, '해외채권_USIG': 0.3, '해외채권_EM': -0.7,
                         '미국주식_성장': -0.6, '미국주식_가치': -0.4,
                         '원자재_금': 0.7, '원자재_원유': 0.5,
                         '환율_USDKRW': -0.5, '환율_DXY': 0.4},
    '부동산':           {'국내주식': 0.2,  '국내채권': 0.0,  '해외주식': 0.0,  '해외채권': 0.0,
                         '해외채권_USHY': 0.0, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                         '미국주식_성장': 0.0, '미국주식_가치': 0.1,
                         '원자재_금': 0.0, '원자재_원유': 0.0,
                         '환율_USDKRW': 0.0, '환율_DXY': 0.0},
    '관세_무역':        {'국내주식': -0.5, '국내채권': 0.1,  '해외주식': -0.6, '해외채권': 0.0,
                         '해외채권_USHY': -0.3, '해외채권_USIG': 0.1, '해외채권_EM': -0.5,
                         '미국주식_성장': -0.7, '미국주식_가치': -0.3,
                         '원자재_금': 0.3, '원자재_원유': -0.2,
                         '환율_USDKRW': -0.4, '환율_DXY': 0.3},
    '크립토':           {'국내주식': 0.1,  '국내채권': 0.0,  '해외주식': 0.2,  '해외채권': 0.0,
                         '해외채권_USHY': 0.0, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                         '미국주식_성장': 0.3, '미국주식_가치': 0.0,
                         '원자재_금': 0.1, '원자재_원유': 0.0,
                         '환율_USDKRW': 0.0, '환율_DXY': 0.0},
    '테크_AI_반도체':   {'국내주식': 0.6,  '국내채권': 0.0,  '해외주식': 0.8,  '해외채권': 0.0,
                         '해외채권_USHY': 0.1, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                         '미국주식_성장': 0.9, '미국주식_가치': 0.1,
                         '원자재_금': 0.0, '원자재_원유': 0.0,
                         '환율_USDKRW': 0.1, '환율_DXY': 0.0},
}


# ═══════════════════════════════════════════════════════
# HTML 클리닝
# ═══════════════════════════════════════════════════════

import html as _html_mod

def _clean_html(text: str) -> str:
    """HTML 엔티티 디코딩 + 태그 제거"""
    if not text:
        return ''
    text = _html_mod.unescape(text)
    text = re.sub(r'<[^>]+>', '', text)
    return text.strip()


# ═══════════════════════════════════════════════════════
# Anthropic API 헬퍼
# ═══════════════════════════════════════════════════════

def _get_api_key():
    key = os.getenv('ANTHROPIC_API_KEY')
    if not key:
        try:
            from market_research.core.constants import ANTHROPIC_API_KEY
            key = ANTHROPIC_API_KEY
        except ImportError:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                'ce', BASE_DIR / 'comment_engine.py')
            ce = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ce)
            key = ce.ANTHROPIC_API_KEY
    return key


def _call_haiku(prompt: str, max_tokens: int = 2000) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=_get_api_key())
    response = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    return response.content[0].text.strip()


def _parse_json_response(text: str):
    from market_research.core.json_utils import parse_json_response
    return parse_json_response(text, expect='array')


# ═══════════════════════════════════════════════════════
# 분류 로직
# ═══════════════════════════════════════════════════════

def _build_classification_prompt(articles: list[dict]) -> str:
    """배치 분류 프롬프트 생성 (뉴스용)"""
    topic_list = ', '.join(TOPIC_TAXONOMY)

    article_lines = []
    for i, a in enumerate(articles):
        title = _clean_html(a.get('title', ''))[:120]
        desc = _clean_html(a.get('description', ''))[:150]
        article_lines.append(f'{i+1}. [{a.get("source", "")}] {title}\n   {desc}')

    return f"""뉴스 기사를 거시 금융 시장 분석 관점에서 분류하세요.

## 분류 체계 (14개 주제)
{topic_list}

## 토픽 판정 기준: "시장 영향 자산" 우선
- primary topic = 기사가 가장 직접적으로 영향을 미치는 자산/시장
- 헤드라인이 직접 명시한 자산이 있으면 그것을 우선
- 명시된 자산이 없으면 가장 직접적인 시장 영향 자산
- 다자산이면 지정학/통화정책 같은 원인 토픽 사용

## 분류 규칙
1. 각 기사에 해당하는 주제를 1~3개 태깅 (multi-label)
2. 각 주제에 대해:
   - direction: "positive" (시장/자산에 긍정) 또는 "negative" (부정)
   - intensity: 1-10 (시장 영향 강도. 1=사소, 10=시장 급변)
3. 아래 기사는 topics를 빈 배열 []로:
   - 개별 종목/ETF/IPO 분석 (거시 파급 없는 것)
   - 자산운용사/펀드 상품 소개, 운용사 브리핑
   - 산업/섹터 뉴스 (시장점유율, 공장 건설 등)
   - 순수 군사/전쟁 속보 (시장 영향 언급 없는 것)
   - 순수 정치/외교, 스포츠, 연예, 과학 등
4. 유동성_크레딧은 좁게: 레포/크로스커런시/TGA/회사채 스프레드만
   - 중앙은행 발언 → 통화정책
   - 환율 → 환율_FX
   - 펀드/ETF → 빈 배열
5. 시장영향 자산 우선 규칙:
   - 제목에 oil price/유가 명시 → 에너지_원자재 (지정학 아님)
   - 제목에 금값/gold price 명시 → 귀금속_금 (물가 아님)
   - 제목에 통화명+환율 수치 명시 → 환율_FX (지정학 아님)
   - 중앙은행(Fed/ECB/BOK) 주체 + 발언/결정 → 통화정책 (달러_글로벌유동성 아님)

## 기사 목록
{chr(10).join(article_lines)}

## 응답 형식 (JSON 배열만, 설명 없이)
[
  {{"id": 1, "topics": [{{"topic": "금리_채권", "direction": "negative", "intensity": 7}}]}},
  {{"id": 2, "topics": []}}
]"""


def _build_research_classification_prompt(articles: list[dict]) -> str:
    """리서치 리포트 전용 분류 프롬프트.

    source_type='naver_research' 기사는 종목 분석/ETF 소개 필터를 끄고,
    리포트가 시사하는 거시 뷰 / 자산배분 뷰를 14개 taxonomy 안에서 뽑는다.
    taxonomy는 뉴스와 동일.
    """
    topic_list = ', '.join(TOPIC_TAXONOMY)

    article_lines = []
    for i, a in enumerate(articles):
        title = _clean_html(a.get('title', ''))[:160]
        desc = _clean_html(a.get('description', ''))[:400]
        broker = a.get('_raw_broker') or a.get('source', '')
        cat = a.get('_raw_category', '')
        article_lines.append(f'{i+1}. [{broker} / {cat}] {title}\n   {desc}')

    return f"""증권사 리서치 리포트의 거시 관점을 14개 토픽으로 분류하세요.

## 분류 체계 (14개 주제, 뉴스와 동일)
{topic_list}

## 리서치 분류 규칙 (뉴스와 다름)
1. 입력은 증권사 리서치 리포트 (경제분석/시황/투자/산업/채권 카테고리).
   뉴스와 달리 리포트는 거의 대부분 거시 해석을 담고 있으므로 **빈 배열은 예외적**이어야 한다.
2. 각 리포트에 해당하는 주제를 1~3개 태깅 (multi-label).
3. 각 주제에 대해:
   - direction: "positive" (해당 자산/시장에 긍정 시사) / "negative" (부정 시사) / "neutral" (중립·혼재)
   - intensity: 1-10 (리포트가 다루는 비중·강조도. 1=부차 언급, 10=리포트 핵심 주제)
4. **리포트 제목에 종목명/ETF명이 있어도**, 그 종목을 통해 해석하려는 거시 주제가 있으면 태깅한다.
   - 예: "키움 반도체 전망" → 테크_AI_반도체 positive, (경기_소비 보조)
   - 예: "미국 HY 스프레드 점검" → 유동성_크레딧, 금리_채권
   - 예: "삼성전자 분기 실적" 같은 **순수 개별 종목 실적 분석**은 빈 배열 허용 (리서치 중에서도 종목 단일 리포트)
5. 카테고리 힌트:
   - economy / debenture: 통화정책 / 금리_채권 / 물가_인플레이션 / 경기_소비 / 유동성_크레딧 중심
   - market_info: 증시 시황 → 테크_AI_반도체 / 경기_소비 / 환율_FX 중 리포트가 실제 다룬 것
   - invest: 자산배분·포트폴리오 뷰 → 관련 자산군 토픽 전부 태깅
   - industry: 섹터 산업뷰 → 섹터에 대응하는 taxonomy 토픽 (반도체→테크_AI_반도체, 정유→에너지_원자재 등)
6. direction 판정이 애매하면 "neutral"을 허용하지만, intensity는 낮춰라(3~5).
7. **"주가 목표가 상향/하향" 한 줄 리포트, 단순 공모주/IPO 소개**는 빈 배열로.

## 리포트 목록
{chr(10).join(article_lines)}

## 응답 형식 (JSON 배열만, 설명 없이)
[
  {{"id": 1, "topics": [{{"topic": "금리_채권", "direction": "negative", "intensity": 7}}, {{"topic": "통화정책", "direction": "neutral", "intensity": 5}}]}},
  {{"id": 2, "topics": []}}
]"""


def _build_narrative_candidate_prompt(articles: list[dict]) -> str:
    """미분류 기사에서 신규 내러티브 후보 키워드 추출"""
    lines = []
    for i, a in enumerate(articles[:30]):  # 최대 30건
        title = a.get('title', '')[:120]
        lines.append(f'{i+1}. [{a.get("source", "")}] {title}')

    return f"""다음 뉴스 기사들은 기존 21개 금융 테마에 분류되지 않은 기사입니다.
이 기사들에서 발견되는 새로운 시장 내러티브(트렌드/이슈)를 추출하세요.

## 미분류 기사
{chr(10).join(lines)}

## 응답 형식 (JSON 배열만)
[
  {{"keyword": "키워드/주제명", "count": 관련기사수, "description": "이 내러티브가 시장에 미칠 수 있는 영향 한줄 설명"}}
]

최대 5개만 추출. 금융과 완전 무관한 기사(스포츠, 연예 등)는 무시."""


# LLM이 자주 틀리는 근접 오타/변형 → 정상 토픽 수동 매핑
_TOPIC_ALIAS = {
    # 기존 오타
    '관제': '관세_무역', '달Dollar': '환율_FX', '달dollar': '환율_FX',
    # 기존 토픽명 → V2 매핑
    '금리': '금리_채권', '미국채': '금리_채권',
    '물가': '물가_인플레이션', '관세': '관세_무역',
    '유가_에너지': '에너지_원자재', '유가': '에너지_원자재',
    # 유가_에너지 깨진 변형 → 에너지_원자재
    '유가_에너': '에너지_원자재',
    '금': '귀금속_금', '안전자산': '귀금속_금',
    '비트코인_크립토': '크립토', '비트코인': '크립토', '비트코': '크립토',
    'AI_반도체': '테크_AI_반도체', 'AI_반도': '테크_AI_반도체',
    '한국_원화': '환율_FX', '중국_위안화': '환율_FX', '엔화_캐리': '환율_FX',
    '유럽_ECB': '통화정책', '유로달러': '달러_글로벌유동성', '달러': '환율_FX',
    '유동성_배관': '유동성_크레딧',
    '이민_노동': '경기_소비', '저출산_인구': '경기_소비',
    # LLM 자체 생성 토픽
    '금융': '금리_채권', '금융안정': '금리_채권', '금융위기': '금리_채권',
    '재정': '통화정책', '에너지': '에너지_원자재', '원자재': '귀금속_금',
    '위험선호': '귀금속_금', '거시경제': '경기_소비', '경기': '경기_소비',
    '미국증시': '테크_AI_반도체', '한국증시': '환율_FX', '환율': '환율_FX',
    '기술': '테크_AI_반도체',
}


def _sanitize_topic(raw_topic: str) -> str:
    """LLM이 반환한 토픽명을 TOPIC_TAXONOMY whitelist와 대조.

    정확 일치 → 그대로 반환.
    수동 alias → 매핑된 토픽 반환.
    불일치 → 가장 긴 공통 prefix를 가진 정상 토픽으로 매핑.
    공통 prefix 부족 → '' (무시).
    """
    if raw_topic in _TOPIC_SET:
        return raw_topic
    if raw_topic in _TOPIC_ALIAS:
        return _TOPIC_ALIAS[raw_topic]
    # alias key의 prefix로 시작하는지 체크 (깨진 토픽 복구)
    for alias_key, alias_val in _TOPIC_ALIAS.items():
        if raw_topic.startswith(alias_key) and len(raw_topic) > len(alias_key):
            return alias_val
    if not raw_topic or len(raw_topic) < 2:
        return ''
    # 가장 긴 공통 prefix를 가진 정상 토픽 찾기
    best_match = ''
    best_overlap = 0
    for valid in TOPIC_TAXONOMY:
        overlap = 0
        for a, b in zip(raw_topic, valid):
            if a == b:
                overlap += 1
            else:
                break
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = valid
    # 최소 overlap: 한글 토픽은 2자, 영문/혼합은 3자
    min_overlap = 2 if best_match and ord(best_match[0]) > 0x1100 else 3
    if best_overlap >= min_overlap:
        return best_match
    return ''


# V2에서는 fallback 토픽도 정규 토픽으로 매핑되므로 별도 허용 불필요
_TOPIC_SET = set(TOPIC_TAXONOMY)


def _apply_classification_results(to_classify: list[dict], results) -> None:
    """LLM 응답(results) → to_classify 각 기사에 in-place 필드 기록."""
    if not results or not isinstance(results, list):
        print(f'    분류 응답 파싱 실패')
        return

    for item in results:
        idx = item.get('id', 0) - 1
        if not (0 <= idx < len(to_classify)):
            continue
        a = to_classify[idx]
        raw_topics = item.get('topics', [])
        topics = []
        for t in raw_topics:
            sanitized = _sanitize_topic(t.get('topic', ''))
            if sanitized:
                t['topic'] = sanitized
                topics.append(t)
        a['_classified_topics'] = topics

        # asset impact vector
        impact = {}
        for t in topics:
            topic_name = t.get('topic', '')
            direction_sign = -1 if t.get('direction') == 'negative' else 1
            intensity_scale = t.get('intensity', 5) / 10.0
            sensitivity = TOPIC_ASSET_SENSITIVITY.get(topic_name, {})
            for asset_key, base_val in sensitivity.items():
                score = base_val * direction_sign * intensity_scale
                impact[asset_key] = impact.get(asset_key, 0) + score
        a['_asset_impact_vector'] = {
            k: round(v, 2) for k, v in impact.items() if abs(v) >= 0.3
        }
        if topics:
            a['asset_class_original'] = a.get('asset_class', a.get('category', ''))
            primary = max(topics, key=lambda t: t.get('intensity', 0))
            a['asset_class'] = _topic_to_asset_class(primary['topic'])
            a['primary_topic'] = primary['topic']
            a['direction'] = primary.get('direction', 'neutral')
            a['intensity'] = primary.get('intensity', 5)


def classify_batch(articles: list[dict]) -> list[dict]:
    """기사 배치 분류 → 각 기사에 topics, asset_impact_vector 추가.

    source_type 기준으로 두 묶음으로 분기 (Phase 2.5, 2026-04-22):
      - 기본 뉴스: Layer 1 Financial Filter → Layer 2 뉴스용 프롬프트
      - source_type='naver_research': Financial Filter 우회 → 리서치 전용 프롬프트
    각 묶음은 별도의 LLM call로 분류하고, 결과는 공통 처리기로 기사에 기록.
    """
    news_bucket: list[dict] = []
    research_bucket: list[dict] = []

    for a in articles:
        if '_classified_topics' in a:
            continue
        if a.get('source_type') == 'naver_research':
            # 리서치는 Financial Filter 건너뛰고 전부 LLM으로 보낸다
            a['_is_macro_financial'] = True
            research_bucket.append(a)
            continue
        is_fin, reason = is_macro_financial(a)
        if not is_fin:
            a['_classified_topics'] = []
            a['_filter_reason'] = reason
            a['_is_macro_financial'] = False
        else:
            a['_is_macro_financial'] = True
            news_bucket.append(a)

    # 뉴스 묶음 — 기존 프롬프트
    if news_bucket:
        prompt = _build_classification_prompt(news_bucket)
        try:
            text = _call_haiku(prompt, max_tokens=3000)
            results = _parse_json_response(text)
            _apply_classification_results(news_bucket, results)
        except Exception as exc:
            print(f'    뉴스 배치 분류 실패 ({len(news_bucket)}건): {type(exc).__name__}: {exc}')
            for a in news_bucket:
                if '_classified_topics' not in a:
                    a['_classify_error'] = str(exc)[:100]

    # 리서치 묶음 — 전용 프롬프트
    if research_bucket:
        prompt = _build_research_classification_prompt(research_bucket)
        try:
            text = _call_haiku(prompt, max_tokens=3000)
            results = _parse_json_response(text)
            _apply_classification_results(research_bucket, results)
            # 리서치 소스 분류 경로를 추적 가능하게 마킹
            for a in research_bucket:
                if '_classified_topics' in a:
                    a['_classifier_prompt'] = 'research_v1'
        except Exception as exc:
            print(f'    리서치 배치 분류 실패 ({len(research_bucket)}건): {type(exc).__name__}: {exc}')
            for a in research_bucket:
                if '_classified_topics' not in a:
                    a['_classify_error'] = str(exc)[:100]

    return articles


def _topic_to_asset_class(topic: str) -> str:
    """V2 14개 토픽 → 기존 호환 asset_class 매핑"""
    mapping = {
        '통화정책': '매크로', '금리_채권': '해외채권',
        '물가_인플레이션': '매크로', '경기_소비': '매크로',
        '유동성_크레딧': '매크로', '환율_FX': '통화',
        '달러_글로벌유동성': '통화', '에너지_원자재': '원자재',
        '귀금속_금': '원자재', '지정학': '매크로',
        '부동산': '대체투자', '관세_무역': '매크로',
        '크립토': '대체투자', '테크_AI_반도체': '해외주식',
    }
    return mapping.get(topic, '매크로')


def extract_narrative_candidates(unclassified: list[dict]) -> list[dict]:
    """미분류 기사에서 신규 내러티브 후보 추출"""
    if not unclassified:
        return []
    prompt = _build_narrative_candidate_prompt(unclassified)
    try:
        text = _call_haiku(prompt, max_tokens=800)
        candidates = _parse_json_response(text)
        if isinstance(candidates, list):
            return candidates
    except Exception as exc:
        print(f'  내러티브 후보 추출 실패: {exc}')
    return []


# ═══════════════════════════════════════════════════════
# 메인 함수
# ═══════════════════════════════════════════════════════

def classify_month(month_str: str, batch_size: int = 20) -> dict:
    """
    월별 뉴스 전체 분류.

    Args:
        month_str: 'YYYY-MM' 형식
        batch_size: Haiku 배치 크기 (기본 20)

    Returns:
        {"total": N, "classified": M, "unclassified": K, "narrative_candidates": [...]}
    """
    news_file = NEWS_DIR / f'{month_str}.json'
    if not news_file.exists():
        print(f'  {news_file} 없음')
        return {"total": 0, "classified": 0, "unclassified": 0}

    data = json.loads(news_file.read_text(encoding='utf-8'))
    articles = data.get('articles', [])
    if not articles:
        print(f'  {month_str}: 기사 없음')
        return {"total": 0, "classified": 0, "unclassified": 0}

    print(f'\n── 뉴스 분류: {month_str} ({len(articles)}건) ──')

    # 이미 분류된 기사 스킵
    to_classify = [a for a in articles if '_classified_topics' not in a]
    already_done = len(articles) - len(to_classify)
    if already_done:
        print(f'  이미 분류됨: {already_done}건, 미분류: {len(to_classify)}건')

    # 전량 분류 (배치당 ~$0.007, 월 1,000건 기준 ~$0.35 — 비용 무시 가능)

    if not to_classify:
        print(f'  전체 분류 완료')
        return {"total": len(articles), "classified": len(articles), "unclassified": 0}

    # 배치 처리 (50배치마다 중간 저장)
    SAVE_INTERVAL = 50
    total_batches = (len(to_classify) + batch_size - 1) // batch_size
    for i in range(0, len(to_classify), batch_size):
        batch = to_classify[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f'  배치 {batch_num}/{total_batches} ({len(batch)}건)...', end='', flush=True)
        classify_batch(batch)
        print(' 완료')
        time.sleep(0.5)  # rate limit
        # 중간 저장 — 프로세스 중단 시 분류 결과 보존
        if batch_num % SAVE_INTERVAL == 0:
            data['articles'] = articles
            safe_write_news_json(news_file, data)
            done_so_far = sum(1 for a in articles if '_classified_topics' in a)
            print(f'  [중간 저장] {done_so_far}/{len(articles)}건 분류됨')

    # 미분류 집계
    unclassified = [a for a in articles if not a.get('_classified_topics')]
    classified = len(articles) - len(unclassified)

    print(f'  결과: 분류됨 {classified}/{len(articles)} ({classified/len(articles)*100:.1f}%)')
    print(f'  미분류: {len(unclassified)}건')

    # 미분류 기사 → 신규 내러티브 후보 추출
    narrative_candidates = []

    # API 실패 건 (재시도 필요)
    api_failed = [a for a in articles if '_classified_topics' not in a]
    if api_failed:
        print(f'  API 미처리: {len(api_failed)}건 (재시도 필요)')

    # 금융 무관 판정 (빈 topics) 중 금융 소스에서 온 기사 → 내러티브 후보 추출 대상
    FINANCE_SOURCES = {'SeekingAlpha', 'Benzinga', 'Reuters', 'CNBC', 'Bloomberg',
                       'Financial Times', 'The Wall Street Journal', 'MarketWatch',
                       'Barron\'s', 'TheStreet', 'Investor\'s Business Daily',
                       'Fortune', 'Forbes', '네이버금융', 'Seeking Alpha'}
    empty_from_finance = [
        a for a in articles
        if isinstance(a.get('_classified_topics'), list)
        and len(a['_classified_topics']) == 0
        and a.get('source', '') in FINANCE_SOURCES
    ]
    non_finance_noise = sum(
        1 for a in articles
        if isinstance(a.get('_classified_topics'), list)
        and len(a['_classified_topics']) == 0
        and a.get('source', '') not in FINANCE_SOURCES
    )
    if non_finance_noise:
        print(f'  금융 무관 노이즈: {non_finance_noise}건 (비금융 소스)')
    if empty_from_finance:
        print(f'  금융 소스인데 빈 topics: {len(empty_from_finance)}건 → 내러티브 후보 추출')
        narrative_candidates = extract_narrative_candidates(empty_from_finance[:30])
    elif api_failed:
        narrative_candidates = extract_narrative_candidates(api_failed[:30])

    if narrative_candidates:
        print(f'  신규 내러티브 후보: {len(narrative_candidates)}개')
        for nc in narrative_candidates:
            print(f'    - {nc.get("keyword", "?")} ({nc.get("count", 0)}건): {nc.get("description", "")}')

    # JSON 저장
    data['articles'] = articles
    data['_classification_meta'] = {
        'classified_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'total': len(articles),
        'classified': classified,
        'unclassified': len(unclassified),
        'topic_taxonomy_version': '14_v2',
    }
    safe_write_news_json(news_file, data)
    print(f'  저장 완료: {news_file}')

    # 내러티브 후보 별도 저장
    if narrative_candidates:
        existing = safe_read_json_list(CANDIDATES_FILE)
        entry = {
            'month': month_str,
            'extracted_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'candidates': narrative_candidates,
        }
        existing.append(entry)
        safe_write_json_list(CANDIDATES_FILE, existing)

    return {
        "total": len(articles),
        "classified": classified,
        "unclassified": len(unclassified),
        "narrative_candidates": narrative_candidates,
    }


def classify_daily(date_str: str, batch_size: int = 20) -> dict:
    """
    일일 뉴스 분류 (Daily Incremental Mode용).
    당일 날짜의 기사만 필터하여 분류.

    Phase 2 (2026-04-21): 2 소스 merge 지원.
      - news/{month}.json  (기존 뉴스)
      - naver_research/adapted/{month}.json  (adapter 산출, source_type='naver_research')
    두 소스를 in-memory로 concat 해서 date 필터 + classify한 뒤 각각의 파일로 분리 저장.
    raw news 파일은 naver_research 기사로 오염되지 않는다.
    """
    # YYYY-MM-DD → YYYY-MM
    month_str = date_str[:7]
    news_file = NEWS_DIR / f'{month_str}.json'

    # news 로드 (없으면 빈 구조)
    if news_file.exists():
        news_data = json.loads(news_file.read_text(encoding='utf-8'))
        news_articles = news_data.get('articles', [])
    else:
        news_data = {'month': month_str, 'articles': []}
        news_articles = news_data['articles']

    # naver_research adapted 로드 (있으면)
    try:
        from market_research.collect.naver_research_adapter import (
            adapted_path as _nr_adapted_path,
            load_adapted as _nr_load_adapted,
        )
        nr_file = _nr_adapted_path(month_str)
        nr_articles = _nr_load_adapted(month_str) if nr_file.exists() else []
    except Exception as exc:
        print(f'  [naver_research adapter merge skipped: {exc}]')
        nr_file = None
        nr_articles = []

    if not news_file.exists() and not nr_articles:
        return {"total": 0, "classified": 0}

    # 2 소스 merge (reference 공유 — classify_batch in-place 수정이 원본에도 반영됨)
    merged = news_articles + nr_articles

    # 당일 기사만 필터
    daily = [a for a in merged if a.get('date', '') == date_str and '_classified_topics' not in a]
    if not daily:
        print(f'  {date_str}: 분류할 기사 없음 (news={len(news_articles)}, naver_research={len(nr_articles)})')
        return {"total": 0, "classified": 0}

    nr_in_daily = sum(1 for a in daily if a.get('source_type') == 'naver_research')
    print(f'  {date_str}: {len(daily)}건 분류 중... (news {len(daily) - nr_in_daily} + naver_research {nr_in_daily})')
    for i in range(0, len(daily), batch_size):
        batch = daily[i:i + batch_size]
        classify_batch(batch)
        time.sleep(0.3)

    classified = sum(1 for a in daily if a.get('_classified_topics'))
    print(f'  분류 완료: {classified}/{len(daily)}건')

    # 저장 — source 분리. 각 article 객체는 classify_batch에서 in-place 수정됐으므로
    # 원본 list (news_articles / nr_articles) 안에서 그대로 보존됨.
    if news_file.exists() or news_articles:
        news_data['articles'] = news_articles
        safe_write_news_json(news_file, news_data)

    if nr_articles and nr_file is not None:
        nr_payload = {
            'month': month_str,
            'source_type': 'naver_research',
            'total': len(nr_articles),
            'articles': nr_articles,
        }
        safe_write_news_json(nr_file, nr_payload)

    return {
        "total": len(daily),
        "classified": classified,
        "news_count": len(daily) - nr_in_daily,
        "naver_research_count": nr_in_daily,
    }


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    if len(sys.argv) > 1:
        month = sys.argv[1]
    else:
        # 최신 뉴스 파일
        files = sorted(NEWS_DIR.glob('202*.json'))
        if not files:
            print('뉴스 파일 없음')
            sys.exit(1)
        month = files[-1].stem

    result = classify_month(month)
    print(f'\n완료: {result}')
