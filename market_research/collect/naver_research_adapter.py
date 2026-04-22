# -*- coding: utf-8 -*-
"""
Naver Research adapter — Phase 2 (plan_naver_research.md §9 + naver_research_phase2.md).

Phase 1 raw record (`data/naver_research/raw/{category}/{YYYY-MM}.json`) 를
기존 뉴스 파이프라인(news_classifier / salience / graph_rag / vectorDB)이 먹을 수 있는
**article-like dict** 로 변환하는 얇은 계층.

출력은 `data/naver_research/adapted/{YYYY-MM}.json` 월별 단일 파일에 저장한다.
raw는 오염시키지 않는다.

Phase 2 범위 (포함):
    - load_naver_research_records: raw 월별 JSON 로드 (5 카테고리 union)
    - to_article_like: 기존 article dict 스키마로 1:1 매핑
    - apply_research_quality_heuristic: TIER band + score + adapter flags
    - build_naver_research_articles: 전체 파이프
    - save_adapted / load_adapted: 월별 단일 파일 IO

Phase 2 제외 (명시적):
    - classifier / salience / graph_rag / vectorDB 편입 자체는 여기서 하지 않음
    - Streamlit UI, debate 호출, PDF 파싱
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from market_research.core.json_utils import safe_read_news_json, safe_write_news_json


# ── 경로 ──

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / 'data' / 'naver_research' / 'raw'
ADAPTED_DIR = BASE_DIR / 'data' / 'naver_research' / 'adapted'

CATEGORIES = ('economy', 'market_info', 'invest', 'industry', 'debenture')

# Quality heuristic 파라미터 (plan_naver_research.md §9 초안 반영)
TIER1_CATEGORIES = {'economy', 'debenture', 'industry'}
TIER2_CATEGORIES = {'market_info', 'invest'}

SHORT_SUMMARY_THRESHOLD = 120        # summary_char_len 미만 → TIER3 하향
PDF_RICH_THRESHOLD = 200_000         # pdf_bytes 이상 → tier up 고려

TIER_SCORE = {'TIER1': 1.0, 'TIER2': 0.7, 'TIER3': 0.3}

# adapter가 하향 판단에 반영하는 raw warning codes
DOWNGRADE_WARNINGS = {
    'detail_no_summary_block',
    'summary_too_short',
    'empty_summary',
}
MINOR_DOWNGRADE_WARNINGS = {'broker_missing'}


# ══════════════════════════════════════════════════════════════════════════════
# raw 로딩
# ══════════════════════════════════════════════════════════════════════════════

def load_naver_research_records(
    month: str,
    categories: Iterable[str] | None = None,
) -> list[dict]:
    """`data/naver_research/raw/{category}/{month}.json` 5 카테고리 union 로드.

    Args:
        month: YYYY-MM
        categories: 지정 안 하면 5 카테고리 전부

    Returns:
        raw article dict 리스트 (변환 전 원본). 없으면 [].
    """
    cats = list(categories) if categories else list(CATEGORIES)
    out: list[dict] = []
    for cat in cats:
        p = RAW_DIR / cat / f'{month}.json'
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding='utf-8'))
        arts = data.get('articles', [])
        out.extend(arts)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 스키마 변환
# ══════════════════════════════════════════════════════════════════════════════

def to_article_like(record: dict) -> dict:
    """raw record 1건 → article-like dict 1건.

    기존 뉴스 스키마(`title, date, source, url, description, source_type, ...`)에 맞춰
    최소 필드만 채우고, raw 고유 정보는 `_raw_*`, adapter 산출은 `_research_*` / `_adapter_*`로 보존.
    """
    title = record.get('title', '') or ''
    date = record.get('date', '') or ''
    broker = record.get('broker') or ''
    category = record.get('category', '') or ''
    url = record.get('detail_url', '') or ''
    summary_text = record.get('summary_text', '') or ''
    summary_char_len = int(record.get('summary_char_len', 0) or 0)
    has_pdf = bool(record.get('has_pdf'))
    pdf_bytes = record.get('pdf_bytes')
    nid = record.get('nid')
    dedupe_key = record.get('dedupe_key', '') or ''
    warnings = list(record.get('_warnings', []) or [])
    broker_source = record.get('broker_source')

    source = broker if broker else category  # broker 우선, 없으면 category fallback

    return {
        # 기존 뉴스 article 스키마 호환 필드
        'title': title,
        'date': date,
        'source': source,
        'url': url,
        'description': summary_text,
        'source_type': 'naver_research',

        # raw 원본 보존 (adapter 경계 분리)
        '_raw_category': category,
        '_raw_nid': nid,
        '_raw_dedupe_key': dedupe_key,
        '_raw_has_pdf': has_pdf,
        '_raw_pdf_bytes': pdf_bytes,
        '_raw_summary_char_len': summary_char_len,
        '_raw_broker': broker,
        '_raw_broker_source': broker_source,
        '_raw_warnings': warnings,

        # adapter quality 산출 (apply_research_quality_heuristic에서 채움)
        '_research_quality_band': None,
        '_research_quality_score': None,
        '_adapter_flags': [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Quality Heuristic
# ══════════════════════════════════════════════════════════════════════════════

def apply_research_quality_heuristic(article: dict) -> dict:
    """article-like dict에 `_research_quality_band / _research_quality_score / _adapter_flags` 채움.

    규칙 (plan_naver_research.md §9 초안):
        - 기본 TIER2
        - category in TIER1_CATEGORIES → TIER1 후보로 승격
        - summary_char_len < 120 → TIER3 하향
        - has_pdf and pdf_bytes > 200_000 → 한 단계 승격 고려
        - raw warning에 detail_no_summary_block/summary_too_short/empty_summary → 하향
        - broker_missing → 소폭 하향
        - description 비어있음 → "empty_description" flag
    """
    flags: list[str] = []

    cat = article.get('_raw_category', '')
    slen = article.get('_raw_summary_char_len', 0) or 0
    has_pdf = bool(article.get('_raw_has_pdf'))
    pdf_bytes = article.get('_raw_pdf_bytes') or 0
    warnings = set(article.get('_raw_warnings', []) or [])
    desc = article.get('description', '') or ''

    # 1) 카테고리 기반 초기 tier
    if cat in TIER1_CATEGORIES:
        band = 'TIER1'
        flags.append('category_tier1')
    elif cat in TIER2_CATEGORIES:
        band = 'TIER2'
        flags.append('category_tier2')
    else:
        band = 'TIER2'
        flags.append('category_unknown')

    # 2) PDF 충실도 → tier up
    if has_pdf and pdf_bytes and pdf_bytes > PDF_RICH_THRESHOLD:
        flags.append('pdf_rich')
        if band == 'TIER2':
            band = 'TIER1'  # 시황/투자도 PDF가 충실하면 tier up
        # TIER1은 이미 최고 — 유지

    # 3) summary 부실 → TIER3 강등
    if slen < SHORT_SUMMARY_THRESHOLD:
        flags.append('short_summary')
        band = 'TIER3'  # 강제 강등 (raw warning보다 우선)

    # 4) raw warning 기반 하향 (short_summary 외)
    if warnings & DOWNGRADE_WARNINGS:
        flags.append('raw_warning_downgrade')
        # TIER1 → TIER2, TIER2 → TIER3, TIER3 유지
        if band == 'TIER1':
            band = 'TIER2'
        elif band == 'TIER2':
            band = 'TIER3'

    # 5) broker missing → 소폭 하향 (TIER1 → TIER2만)
    if warnings & MINOR_DOWNGRADE_WARNINGS:
        flags.append('missing_broker')
        if band == 'TIER1':
            band = 'TIER2'

    # 6) description 비어있음 flag (band는 이미 short_summary에서 처리됐을 가능성)
    if not desc.strip():
        flags.append('empty_description')

    # 7) PDF 존재 flag
    if has_pdf:
        flags.append('has_pdf')

    article['_research_quality_band'] = band
    article['_research_quality_score'] = TIER_SCORE[band]
    article['_adapter_flags'] = flags
    return article


# ══════════════════════════════════════════════════════════════════════════════
# 전체 파이프
# ══════════════════════════════════════════════════════════════════════════════

def build_naver_research_articles(
    month: str,
    categories: Iterable[str] | None = None,
) -> list[dict]:
    """raw 로드 → article-like 변환 → quality heuristic 적용."""
    raw_records = load_naver_research_records(month, categories)
    articles: list[dict] = []
    for rec in raw_records:
        art = to_article_like(rec)
        art = apply_research_quality_heuristic(art)
        articles.append(art)
    return articles


# ══════════════════════════════════════════════════════════════════════════════
# adapted 저장/로딩 (월별 단일 파일)
# ══════════════════════════════════════════════════════════════════════════════

def adapted_path(month: str) -> Path:
    return ADAPTED_DIR / f'{month}.json'


# Phase 2.5 (2026-04-22) merge-on-save:
# 매일 raw 기준 deterministic 재생성이지만, 기존 adapted 파일에 이미 부착돼 있을 수 있는
# downstream 산출 필드는 보존한다. dedupe_key 기준으로 매칭해서 다음 필드만 carry-over:
#   분류기:   _classified_topics, _asset_impact_vector, primary_topic, direction, intensity,
#             asset_class, asset_class_original, _is_macro_financial, _filter_reason,
#             _classify_error, _classifier_prompt
#   refine:   _article_id, _dedup_group_id, is_primary,
#             _event_group_id, _event_source_count,
#             _event_salience, _asset_relevance,
#             _fallback_classified
# 그 외 모든 raw-derived 필드 (title/source/_raw_*/_research_quality_*/_adapter_flags 등) 는
# 새 adapter 산출로 갱신한다. (raw 변경 시 자동 반영되도록)

DOWNSTREAM_PRESERVE_FIELDS = (
    '_classified_topics', '_asset_impact_vector',
    'primary_topic', 'direction', 'intensity',
    'asset_class', 'asset_class_original',
    '_is_macro_financial', '_filter_reason',
    '_classify_error', '_classifier_prompt',
    '_article_id', '_dedup_group_id', 'is_primary',
    '_event_group_id', '_event_source_count',
    '_event_salience', '_asset_relevance',
    '_fallback_classified',
)


def _load_existing_adapted_index(p: Path) -> dict[str, dict]:
    """기존 adapted/{month}.json 을 dedupe_key → article dict 로 인덱싱."""
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for a in data.get('articles', []):
        key = a.get('_raw_dedupe_key') or a.get('dedupe_key')
        if key:
            out[key] = a
    return out


def save_adapted(month: str, articles: list[dict]) -> Path:
    """`data/naver_research/adapted/{month}.json` 저장.

    Phase 2.5 merge-on-save: 기존 파일에 부착된 downstream 필드(_classified_topics 등)는
    dedupe_key 기준으로 carry-over. raw-derived 필드는 새 adapter 출력으로 갱신.
    이로써 매일 adapter 재실행해도 분류/정제 결과가 사라지지 않는다.
    """
    ADAPTED_DIR.mkdir(parents=True, exist_ok=True)
    p = adapted_path(month)

    existing = _load_existing_adapted_index(p)
    preserved = 0
    if existing:
        for a in articles:
            key = a.get('_raw_dedupe_key')
            if not key:
                continue
            old = existing.get(key)
            if not old:
                continue
            for f in DOWNSTREAM_PRESERVE_FIELDS:
                if f in old and f not in a:
                    a[f] = old[f]
                    if f == '_classified_topics':
                        preserved += 1

    payload = {
        'month': month,
        'source_type': 'naver_research',
        'total': len(articles),
        '_merge_on_save_preserved': preserved,
        'articles': articles,
    }
    safe_write_news_json(p, payload)
    return p


def load_adapted(month: str) -> list[dict]:
    """월별 adapted 파일 로드. 없으면 []. safe_read_news_json이 articles list를 반환함."""
    p = adapted_path(month)
    if not p.exists():
        return []
    return safe_read_news_json(p)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description='Naver Research adapter (Phase 2)')
    parser.add_argument('month', help='YYYY-MM')
    parser.add_argument('--category', action='append', choices=list(CATEGORIES), default=None)
    parser.add_argument('--dry-run', action='store_true', help='파일 저장 생략, 통계만 출력')
    args = parser.parse_args()

    articles = build_naver_research_articles(args.month, args.category)
    print(f'[naver_research_adapter] month={args.month} total={len(articles)}')

    # band 분포
    from collections import Counter
    band_dist = Counter(a.get('_research_quality_band') for a in articles)
    print(f'  quality bands: {dict(band_dist)}')

    if not args.dry_run:
        p = save_adapted(args.month, articles)
        print(f'  saved: {p}')
    else:
        print('  dry-run: no file written')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
