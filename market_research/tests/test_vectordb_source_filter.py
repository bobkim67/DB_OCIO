# -*- coding: utf-8 -*-
"""vectorDB source_type filter acceptance (Phase 3).

실행 전에 `news_vectordb.build_index` 로 대상 월 인덱스가 구축돼 있어야 한다.
월 인자는 기본 2026-01~04, CLI 로 override 가능.

판정 4개:
  1. disjoint: id(nr) ∩ id(news) == ∅
  2. union cover: id(nr) ∪ id(news) ⊇ id(all)
  3. 양쪽 nonempty: len(nr) > 0 AND len(news) > 0
  4. metadata: source_type 필드 100%, adapted 쪽 category|broker 최소 하나
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


QUERIES = [
    'Fed rate decision inflation outlook',
    'Korean stock market KOSPI rally',
    'gold price surge safe haven',
    'US Treasury yield curve',
]


def _ids(results: list) -> set:
    return {r.get('id') or r.get('article_id') for r in results}


def _check_month(month: str, top_k: int = 20) -> dict:
    from market_research.analyze.news_vectordb import search, _get_collection
    col = _get_collection(month)
    cnt = col.count()
    out = {'month': month, 'indexed': cnt, 'queries': [], 'failed': []}

    if cnt == 0:
        out['failed'].append('collection_empty')
        return out

    # 4. metadata schema audit — source_type 전량, nr 전용 where 쿼리로 샘플
    peek = col.peek(limit=min(200, cnt))
    metas = peek.get('metadatas', []) or []
    if not metas:
        out['failed'].append('peek_no_metas')
        return out
    has_st = sum(1 for m in metas if m.get('source_type'))
    out['schema_source_type_pct'] = round(has_st / len(metas) * 100, 1)
    if has_st != len(metas):
        out['failed'].append(
            f'source_type_missing ({has_st}/{len(metas)})')

    # nr 메타는 별도 where filter 로 직접 가져와 audit (peek 초입 편향 회피)
    nr_pull = col.get(
        where={'source_type': 'naver_research'}, limit=200,
        include=['metadatas'])
    nr_metas = nr_pull.get('metadatas', []) or []
    out['schema_nr_sample_size'] = len(nr_metas)
    if nr_metas:
        has_cat = sum(1 for m in nr_metas if m.get('category'))
        has_broker = sum(1 for m in nr_metas if m.get('broker'))
        out['schema_nr_category_pct'] = round(has_cat / len(nr_metas) * 100, 1)
        out['schema_nr_broker_pct'] = round(has_broker / len(nr_metas) * 100, 1)
        # either 기준: category 또는 broker 중 하나 이상 (설계 기준)
        either = sum(1 for m in nr_metas if m.get('category') or m.get('broker'))
        out['schema_nr_either_pct'] = round(either / len(nr_metas) * 100, 1)
        if out['schema_nr_either_pct'] < 95.0:
            out['failed'].append(
                f'nr_meta_incomplete: either={out["schema_nr_either_pct"]}%')
    else:
        out['schema_nr_category_pct'] = None
        out['schema_nr_broker_pct'] = None
        out['schema_nr_either_pct'] = None
        # nr 건수 0 이면 acceptance FAIL 조건인데, 이미 nonempty 에서 걸러짐

    # 1~3 per-query
    for q in QUERIES:
        r_all = search(q, month, top_k=top_k, source_type=None)
        r_nr = search(q, month, top_k=top_k, source_type='naver_research')
        r_news = search(q, month, top_k=top_k, source_type='news')
        ids_all = _ids(r_all)
        ids_nr = _ids(r_nr)
        ids_news = _ids(r_news)

        disjoint = ids_nr.isdisjoint(ids_news)
        union_cover = ids_all.issubset(ids_nr | ids_news)
        nonempty = len(r_nr) > 0 and len(r_news) > 0

        out['queries'].append({
            'query': q,
            'all': len(r_all), 'nr': len(r_nr), 'news': len(r_news),
            'disjoint': disjoint, 'union_cover': union_cover,
            'nonempty': nonempty,
        })
        if not disjoint:
            out['failed'].append(f'disjoint_fail: "{q}"')
        if not union_cover:
            out['failed'].append(f'union_cover_fail: "{q}"')
        if not nonempty:
            out['failed'].append(
                f'nonempty_fail: "{q}" nr={len(r_nr)} news={len(r_news)}')

    return out


def main(months: list[str]) -> int:
    overall_fail = False
    for m in months:
        print(f'\n── {m} ──')
        r = _check_month(m)
        print(f'  indexed: {r["indexed"]}')
        print(f'  schema source_type pct: {r.get("schema_source_type_pct")}% '
              f'(peek {min(200, r["indexed"])}건)')
        print(f'  schema nr sample size: {r.get("schema_nr_sample_size")}')
        print(f'  schema nr category pct: {r.get("schema_nr_category_pct")}%')
        print(f'  schema nr broker pct:   {r.get("schema_nr_broker_pct")}%')
        print(f'  schema nr either pct:   {r.get("schema_nr_either_pct")}% '
              f'(acceptance ≥ 95%)')
        for q in r.get('queries', []):
            print(f'  [{q["query"][:40]:<40}] '
                  f'all={q["all"]:<3} nr={q["nr"]:<3} news={q["news"]:<3} '
                  f'disjoint={q["disjoint"]} union={q["union_cover"]} '
                  f'nonempty={q["nonempty"]}')
        if r['failed']:
            print(f'  FAIL: {r["failed"]}')
            overall_fail = True
        else:
            print(f'  PASS')

    print()
    print('OVERALL:', 'FAIL' if overall_fail else 'PASS')
    return 1 if overall_fail else 0


if __name__ == '__main__':
    months = sys.argv[1:] if len(sys.argv) > 1 else ['2026-01', '2026-02', '2026-03', '2026-04']
    sys.exit(main(months))
