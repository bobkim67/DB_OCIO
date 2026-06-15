# -*- coding: utf-8 -*-
"""monygeek 블로그 → research-claim 입력 정규화 (wiki_from_naver_research P1).

monygeek posts.json(블로그 전수) 를 naver_research_adapter 와 동일한 **article-like
dict** 로 변환해, research_claim_extractor 가 두 레인(naver_research / monygeek)을
같은 규약으로 먹게 한다. monygeek 은 관점(view)·역발상 레이어 → source_type='monygeek'.

- raw posts.json 은 오염시키지 않음 (read-only).
- 안정 evidence id(`_article_id`) 를 자체 부여 (refine 파이프라인 비의존).
- LLM 0, IO = posts.json read only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
POSTS_PATH = BASE_DIR / 'data' / 'monygeek' / 'posts.json'


def _article_id(source: str, date: str, title: str) -> str:
    """title+date+source MD5 12 hex (core.dedupe.assign_article_ids 컨벤션 동일)."""
    key = f"{title}|{date}|{source}".encode('utf-8')
    return hashlib.md5(key).hexdigest()[:12]


def load_monygeek_posts() -> list[dict]:
    """posts.json 전수 로드 (list). 없으면 []."""
    if not POSTS_PATH.exists():
        return []
    try:
        data = json.loads(POSTS_PATH.read_text(encoding='utf-8'))
    except Exception:
        return []
    return data if isinstance(data, list) else data.get('posts', [])


def to_article_like(post: dict) -> dict:
    """monygeek post 1건 → article-like dict (naver_research_adapter 스키마 미러)."""
    title = (post.get('title') or '').strip()
    date = (post.get('date') or '').strip()
    content = post.get('content') or ''
    url = post.get('url') or ''
    log_no = post.get('log_no')
    category = post.get('blog_category') or post.get('category') or ''
    source = 'monygeek'
    return {
        # 뉴스 article 스키마 호환
        'title': title,
        'date': date,
        'source': source,
        'url': url,
        'description': content,
        'source_type': 'monygeek',
        # 안정 evidence id (자체 부여)
        '_article_id': _article_id(source, date, title),
        # raw 보존 (adapter 경계)
        '_raw_log_no': log_no,
        '_raw_blog_category': category,
        # 귀속 (broker_author 자리 — 블로그는 단일 author)
        '_raw_broker': 'monygeek',
        '_raw_category': category,
    }


def build_monygeek_articles(month: str) -> list[dict]:
    """해당 월(YYYY-MM) monygeek post → article-like 리스트.

    date 가 `YYYY-MM-DD` prefix 로 month 매칭되는 post 만. title 빈 건 제외.
    """
    out: list[dict] = []
    for p in load_monygeek_posts():
        date = (p.get('date') or '').strip()
        if not date.startswith(month):
            continue
        art = to_article_like(p)
        if not art['title']:
            continue
        out.append(art)
    return out
