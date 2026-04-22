# -*- coding: utf-8 -*-
"""Article Stream — vectorDB / GraphRAG 공통 입력 진입점.

Phase 3 (2026-04-22): news 와 naver_research adapted 두 소스를 같은 규약으로
로드해서 downstream (vectorDB 인덱싱, GraphRAG 엔티티 추출) 이 동일한 stream 을
바라보게 한다.

정책:
  - cross-source dedupe 는 **하지 않는다** (handoff 고정원칙 #6 저장소 분리).
  - 각 소스 내부 dedupe / 분류 / salience 는 이미 적용된 상태로 로드된다.
  - news 기사에 `source_type` 필드가 없으면 'news' 로 강제 주입 (legacy 대응).
  - 모든 downstream 은 `source_of(a)` 로 source 판정 → 'news' | 'naver_research'.
"""
from __future__ import annotations

import json
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent  # market_research/
NEWS_DIR = _BASE / 'data' / 'news'

DEFAULT_SOURCES = ('news', 'naver_research')


def source_of(article: dict) -> str:
    """기사의 source_type 판정. 없으면 'news' 로 간주."""
    return article.get('source_type') or 'news'


def _load_news(month: str) -> list[dict]:
    p = NEWS_DIR / f'{month}.json'
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return []
    arts = data.get('articles', [])
    # source_type 강제 주입 (downstream filter 정합성)
    for a in arts:
        if not a.get('source_type'):
            a['source_type'] = 'news'
    return arts


def _load_adapted(month: str) -> list[dict]:
    try:
        from market_research.collect.naver_research_adapter import load_adapted
    except Exception:
        return []
    arts = load_adapted(month) or []
    for a in arts:
        if a.get('source_type') != 'naver_research':
            a['source_type'] = 'naver_research'
    return arts


def load_month_articles(month: str, sources=DEFAULT_SOURCES) -> list[dict]:
    """월별 두 소스 합친 article 리스트.

    Args:
        month: 'YYYY-MM'
        sources: ('news', 'naver_research') 중 부분집합. 기본 둘 다.

    Returns:
        concat 된 리스트. cross-source dedupe 하지 않음. source_type 필드 보장.
    """
    out: list[dict] = []
    if 'news' in sources:
        out.extend(_load_news(month))
    if 'naver_research' in sources:
        out.extend(_load_adapted(month))
    return out


def stream_stats(articles: list[dict]) -> dict:
    """입력 stream 요약 — source_type 별 count."""
    nr = sum(1 for a in articles if source_of(a) == 'naver_research')
    news = sum(1 for a in articles if source_of(a) == 'news')
    return {'total': len(articles), 'news': news, 'naver_research': nr}
