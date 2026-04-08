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

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
NEWS_DIR = BASE_DIR / 'data' / 'news'
CANDIDATES_FILE = BASE_DIR / 'data' / 'narrative_candidates.json'

# ═══════════════════════════════════════════════════════
# 21개 주제 분류 체계
# ═══════════════════════════════════════════════════════

# 기존 18개 + 신규 3개 (지정학, 유동성_배관, 통화정책)
TOPIC_TAXONOMY = [
    '금리', '달러', '이민_노동', '물가', '관세', '안전자산', '미국채',
    '엔화_캐리', '중국_위안화', '유로달러', '유가_에너지', 'AI_반도체',
    '한국_원화', '유럽_ECB', '부동산', '저출산_인구', '비트코인_크립토', '금',
    # 신규 3개
    '지정학',       # 전쟁, 제재, 호르무즈, 이란, 대만, NATO
    '유동성_배관',   # 레포 실패, 담보 가치, 크로스커런시 베이시스, TGA, SRF
    '통화정책',      # Fed/ECB/BOJ/BOK 정책 결정, 점도표, 금리 인하/인상
]

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

TOPIC_ASSET_SENSITIVITY = {
    '금리':          {'국내주식': -0.3, '국내채권': -0.8, '해외주식': -0.5, '해외채권': -0.9,
                      '해외채권_USHY': -0.7, '해외채권_USIG': -0.9, '해외채권_EM': -0.6,
                      '미국주식_성장': -0.7, '미국주식_가치': -0.3,
                      '원자재_금': 0.3, '원자재_원유': -0.2,
                      '환율_USDKRW': -0.4, '환율_DXY': 0.5},
    '달러':          {'국내주식': -0.5, '국내채권': -0.2, '해외주식': -0.3, '해외채권': -0.3,
                      '해외채권_USHY': -0.2, '해외채권_USIG': -0.1, '해외채권_EM': -0.6,
                      '미국주식_성장': -0.2, '미국주식_가치': -0.1,
                      '원자재_금': -0.5, '원자재_원유': -0.3,
                      '환율_USDKRW': -0.8, '환율_DXY': 0.9},
    '이민_노동':     {'국내주식': 0.0,  '국내채권': 0.0,  '해외주식': 0.3,  '해외채권': 0.1,
                      '해외채권_USHY': 0.1, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                      '미국주식_성장': 0.2, '미국주식_가치': 0.3,
                      '원자재_금': 0.0, '원자재_원유': 0.0,
                      '환율_USDKRW': 0.0, '환율_DXY': 0.0},
    '물가':          {'국내주식': -0.3, '국내채권': -0.5, '해외주식': -0.4, '해외채권': -0.6,
                      '해외채권_USHY': -0.4, '해외채권_USIG': -0.7, '해외채권_EM': -0.5,
                      '미국주식_성장': -0.6, '미국주식_가치': -0.2,
                      '원자재_금': 0.4, '원자재_원유': 0.3,
                      '환율_USDKRW': -0.3, '환율_DXY': 0.3},
    '관세':          {'국내주식': -0.5, '국내채권': 0.1,  '해외주식': -0.6, '해외채권': 0.0,
                      '해외채권_USHY': -0.3, '해외채권_USIG': 0.1, '해외채권_EM': -0.5,
                      '미국주식_성장': -0.7, '미국주식_가치': -0.3,
                      '원자재_금': 0.3, '원자재_원유': -0.2,
                      '환율_USDKRW': -0.4, '환율_DXY': 0.3},
    '안전자산':       {'국내주식': -0.4, '국내채권': 0.3,  '해외주식': -0.5, '해외채권': 0.5,
                      '해외채권_USHY': -0.3, '해외채권_USIG': 0.6, '해외채권_EM': -0.4,
                      '미국주식_성장': -0.6, '미국주식_가치': -0.3,
                      '원자재_금': 0.8, '원자재_원유': -0.2,
                      '환율_USDKRW': -0.3, '환율_DXY': 0.5},
    '미국채':        {'국내주식': -0.2, '국내채권': -0.3, '해외주식': -0.3, '해외채권': -0.8,
                      '해외채권_USHY': -0.5, '해외채권_USIG': -0.9, '해외채권_EM': -0.4,
                      '미국주식_성장': -0.4, '미국주식_가치': -0.2,
                      '원자재_금': 0.2, '원자재_원유': -0.1,
                      '환율_USDKRW': -0.2, '환율_DXY': 0.3},
    '엔화_캐리':     {'국내주식': -0.4, '국내채권': 0.0,  '해외주식': -0.5, '해외채권': -0.2,
                      '해외채권_USHY': -0.3, '해외채권_USIG': -0.1, '해외채권_EM': -0.5,
                      '미국주식_성장': -0.6, '미국주식_가치': -0.3,
                      '원자재_금': 0.2, '원자재_원유': -0.1,
                      '환율_USDKRW': -0.4, '환율_DXY': 0.2},
    '중국_위안화':   {'국내주식': -0.5, '국내채권': 0.0,  '해외주식': -0.3, '해외채권': 0.0,
                      '해외채권_USHY': 0.0, '해외채권_USIG': 0.0, '해외채권_EM': -0.6,
                      '미국주식_성장': -0.2, '미국주식_가치': -0.1,
                      '원자재_금': 0.1, '원자재_원유': -0.2,
                      '환율_USDKRW': -0.5, '환율_DXY': 0.3},
    '유로달러':      {'국내주식': -0.3, '국내채권': -0.2, '해외주식': -0.4, '해외채권': -0.5,
                      '해외채권_USHY': -0.4, '해외채권_USIG': -0.3, '해외채권_EM': -0.6,
                      '미국주식_성장': -0.4, '미국주식_가치': -0.3,
                      '원자재_금': 0.3, '원자재_원유': -0.2,
                      '환율_USDKRW': -0.5, '환율_DXY': 0.6},
    '유가_에너지':   {'국내주식': -0.3, '국내채권': -0.2, '해외주식': -0.3, '해외채권': -0.3,
                      '해외채권_USHY': -0.4, '해외채권_USIG': -0.1, '해외채권_EM': -0.3,
                      '미국주식_성장': -0.3, '미국주식_가치': 0.2,
                      '원자재_금': 0.1, '원자재_원유': 0.9,
                      '환율_USDKRW': -0.2, '환율_DXY': 0.1},
    'AI_반도체':     {'국내주식': 0.6,  '국내채권': 0.0,  '해외주식': 0.8,  '해외채권': 0.0,
                      '해외채권_USHY': 0.1, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                      '미국주식_성장': 0.9, '미국주식_가치': 0.1,
                      '원자재_금': 0.0, '원자재_원유': 0.0,
                      '환율_USDKRW': 0.1, '환율_DXY': 0.0},
    '한국_원화':     {'국내주식': 0.7,  '국내채권': 0.2,  '해외주식': 0.0,  '해외채권': 0.0,
                      '해외채권_USHY': 0.0, '해외채권_USIG': 0.0, '해외채권_EM': 0.2,
                      '미국주식_성장': 0.0, '미국주식_가치': 0.0,
                      '원자재_금': 0.0, '원자재_원유': 0.0,
                      '환율_USDKRW': 0.8, '환율_DXY': -0.3},
    '유럽_ECB':      {'국내주식': 0.0,  '국내채권': 0.0,  '해외주식': 0.3,  '해외채권': 0.3,
                      '해외채권_USHY': 0.1, '해외채권_USIG': 0.3, '해외채권_EM': 0.2,
                      '미국주식_성장': 0.2, '미국주식_가치': 0.3,
                      '원자재_금': 0.1, '원자재_원유': 0.1,
                      '환율_USDKRW': 0.1, '환율_DXY': -0.4},
    '부동산':        {'국내주식': 0.2,  '국내채권': 0.0,  '해외주식': 0.0,  '해외채권': 0.0,
                      '해외채권_USHY': 0.0, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                      '미국주식_성장': 0.0, '미국주식_가치': 0.1,
                      '원자재_금': 0.0, '원자재_원유': 0.0,
                      '환율_USDKRW': 0.0, '환율_DXY': 0.0},
    '저출산_인구':   {'국내주식': -0.2, '국내채권': 0.0,  '해외주식': 0.0,  '해외채권': 0.0,
                      '해외채권_USHY': 0.0, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                      '미국주식_성장': 0.0, '미국주식_가치': 0.0,
                      '원자재_금': 0.0, '원자재_원유': 0.0,
                      '환율_USDKRW': 0.0, '환율_DXY': 0.0},
    '비트코인_크립토': {'국내주식': 0.1, '국내채권': 0.0,  '해외주식': 0.2,  '해외채권': 0.0,
                      '해외채권_USHY': 0.0, '해외채권_USIG': 0.0, '해외채권_EM': 0.0,
                      '미국주식_성장': 0.3, '미국주식_가치': 0.0,
                      '원자재_금': 0.1, '원자재_원유': 0.0,
                      '환율_USDKRW': 0.0, '환율_DXY': 0.0},
    '금':            {'국내주식': -0.1, '국내채권': 0.1,  '해외주식': -0.2, '해외채권': 0.2,
                      '해외채권_USHY': 0.0, '해외채권_USIG': 0.2, '해외채권_EM': 0.1,
                      '미국주식_성장': -0.3, '미국주식_가치': 0.0,
                      '원자재_금': 0.9, '원자재_원유': 0.0,
                      '환율_USDKRW': 0.0, '환율_DXY': -0.4},
    '지정학':        {'국내주식': -0.5, '국내채권': 0.2,  '해외주식': -0.6, '해외채권': 0.3,
                      '해외채권_USHY': -0.5, '해외채권_USIG': 0.3, '해외채권_EM': -0.7,
                      '미국주식_성장': -0.6, '미국주식_가치': -0.4,
                      '원자재_금': 0.7, '원자재_원유': 0.5,
                      '환율_USDKRW': -0.5, '환율_DXY': 0.4},
    '유동성_배관':   {'국내주식': -0.3, '국내채권': -0.4, '해외주식': -0.4, '해외채권': -0.5,
                      '해외채권_USHY': -0.7, '해외채권_USIG': -0.3, '해외채권_EM': -0.8,
                      '미국주식_성장': -0.5, '미국주식_가치': -0.3,
                      '원자재_금': 0.2, '원자재_원유': -0.3,
                      '환율_USDKRW': -0.5, '환율_DXY': 0.6},
    '통화정책':      {'국내주식': -0.4, '국내채권': -0.6, '해외주식': -0.5, '해외채권': -0.7,
                      '해외채권_USHY': -0.5, '해외채권_USIG': -0.8, '해외채권_EM': -0.6,
                      '미국주식_성장': -0.7, '미국주식_가치': -0.3,
                      '원자재_금': 0.3, '원자재_원유': -0.2,
                      '환율_USDKRW': -0.4, '환율_DXY': 0.5},
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
    """배치 분류 프롬프트 생성"""
    topic_list = ', '.join(TOPIC_TAXONOMY)

    article_lines = []
    for i, a in enumerate(articles):
        title = _clean_html(a.get('title', ''))[:120]
        desc = _clean_html(a.get('description', ''))[:150]
        article_lines.append(f'{i+1}. [{a.get("source", "")}] {title}\n   {desc}')

    return f"""뉴스 기사를 금융 시장 분석 관점에서 분류하세요.

## 분류 체계 (21개 주제)
{topic_list}

## 분류 규칙
1. 각 기사에 해당하는 주제를 1~3개 태깅 (multi-label)
2. 각 주제에 대해:
   - direction: "positive" (시장/자산에 긍정) 또는 "negative" (부정)
   - intensity: 1-10 (시장 영향 강도. 1=사소, 10=시장 급변)
3. 금융과 무관한 기사(스포츠, 연예, 과학논문, 게임, 요리 등)만 topics를 빈 배열로
4. 다음은 반드시 분류할 것 (빈 배열 금지):
   - 개별 종목/ETF 분석 → 해당 자산군 주제 (예: NVIDIA 분석 → AI_반도체)
   - 투자 전략/자산배분 기사 → 관련 자산군 주제
   - M&A/IPO/기업 뉴스 → 해당 시장 주제 (예: 한국 기업 인수 → 한국_원화)
   - 자산운용사/펀드 뉴스 → 관련 자산군 주제
   - 경제 지표 발표 → 해당 매크로 주제

## 기사 목록
{chr(10).join(article_lines)}

## 응답 형식 (JSON 배열만, 설명 없이)
[
  {{"id": 1, "topics": [{{"topic": "금리", "direction": "negative", "intensity": 7}}]}},
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


def classify_batch(articles: list[dict]) -> list[dict]:
    """기사 배치 분류 → 각 기사에 topics, asset_impact_vector 추가"""
    prompt = _build_classification_prompt(articles)
    try:
        text = _call_haiku(prompt, max_tokens=3000)
        results = _parse_json_response(text)
        if not results or not isinstance(results, list):
            print(f'    분류 응답 파싱 실패')
            return articles

        for item in results:
            idx = item.get('id', 0) - 1
            if 0 <= idx < len(articles):
                a = articles[idx]
                topics = item.get('topics', [])
                a['_classified_topics'] = topics
                # asset impact vector — TOPIC_ASSET_SENSITIVITY 룩업으로 계산
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
                # 기존 asset_class 보존 + 새 분류 적용
                if topics:
                    a['asset_class_original'] = a.get('asset_class', a.get('category', ''))
                    # 최고 intensity 주제를 primary asset_class로 매핑
                    primary = max(topics, key=lambda t: t.get('intensity', 0))
                    a['asset_class'] = _topic_to_asset_class(primary['topic'])
                    a['primary_topic'] = primary['topic']
                    a['direction'] = primary.get('direction', 'neutral')
                    a['intensity'] = primary.get('intensity', 5)

    except Exception as exc:
        print(f'    배치 분류 실패: {exc}')

    return articles


def _topic_to_asset_class(topic: str) -> str:
    """21개 주제 → 기존 호환 asset_class 매핑"""
    mapping = {
        '금리': '해외채권', '달러': '통화', '이민_노동': '매크로',
        '물가': '매크로', '관세': '매크로', '안전자산': '매크로',
        '미국채': '해외채권', '엔화_캐리': '통화', '중국_위안화': '통화',
        '유로달러': '매크로', '유가_에너지': '원자재', 'AI_반도체': '해외주식',
        '한국_원화': '국내주식', '유럽_ECB': '매크로', '부동산': '대체투자',
        '저출산_인구': '매크로', '비트코인_크립토': '대체투자', '금': '원자재',
        '지정학': '매크로', '유동성_배관': '매크로', '통화정책': '매크로',
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

    # 날짜×자산군 상위 N건만 분류 (같은 날 같은 자산군 수백 건 중복 방지)
    MAX_PER_DATE_AC = 50
    from collections import defaultdict
    date_ac_count = defaultdict(int)
    filtered = []
    skipped = 0
    # description 긴 순으로 우선 (내용 있는 기사 우선)
    to_classify.sort(key=lambda a: -len(a.get('description', '')))
    for a in to_classify:
        key = (a.get('date', '')[:10], a.get('asset_class', '일반'))
        if date_ac_count[key] < MAX_PER_DATE_AC:
            filtered.append(a)
            date_ac_count[key] += 1
        else:
            skipped += 1
    if skipped:
        print(f'  날짜×자산군 상한({MAX_PER_DATE_AC}) 초과 스킵: {skipped}건')
    to_classify = filtered

    if not to_classify:
        print(f'  전체 분류 완료')
        return {"total": len(articles), "classified": len(articles), "unclassified": 0}

    # 배치 처리
    total_batches = (len(to_classify) + batch_size - 1) // batch_size
    for i in range(0, len(to_classify), batch_size):
        batch = to_classify[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f'  배치 {batch_num}/{total_batches} ({len(batch)}건)...', end='', flush=True)
        classify_batch(batch)
        print(' 완료')
        time.sleep(0.5)  # rate limit

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
        'topic_taxonomy_version': '21_v1',
    }
    news_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  저장 완료: {news_file}')

    # 내러티브 후보 별도 저장
    if narrative_candidates:
        existing = []
        if CANDIDATES_FILE.exists():
            try:
                existing = json.loads(CANDIDATES_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass
        entry = {
            'month': month_str,
            'extracted_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'candidates': narrative_candidates,
        }
        existing.append(entry)
        CANDIDATES_FILE.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8')

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
    """
    # YYYY-MM-DD → YYYY-MM
    month_str = date_str[:7]
    news_file = NEWS_DIR / f'{month_str}.json'
    if not news_file.exists():
        return {"total": 0, "classified": 0}

    data = json.loads(news_file.read_text(encoding='utf-8'))
    articles = data.get('articles', [])

    # 당일 기사만 필터
    daily = [a for a in articles if a.get('date', '') == date_str and '_classified_topics' not in a]
    if not daily:
        print(f'  {date_str}: 분류할 기사 없음')
        return {"total": 0, "classified": 0}

    print(f'  {date_str}: {len(daily)}건 분류 중...')
    for i in range(0, len(daily), batch_size):
        batch = daily[i:i + batch_size]
        classify_batch(batch)
        time.sleep(0.3)

    classified = sum(1 for a in daily if a.get('_classified_topics'))
    print(f'  분류 완료: {classified}/{len(daily)}건')

    # 저장
    data['articles'] = articles
    news_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    return {"total": len(daily), "classified": classified}


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
