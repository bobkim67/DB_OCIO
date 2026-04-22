# -*- coding: utf-8 -*-
"""
Phase 2.5 후속 (Option A-strict + intensity-fix) 재측정.

비교 3가지 (모두 동일 분류 결과 위에서 salience만 재계산):
  PRE_RAW         : cap off, intensity-fix off  (Phase 2.5 step2 직후 상태)
  POST_CAP_ONLY   : cap=0.70, intensity-fix off (이전 회차)
  POST_CAP_FIX    : cap=0.70, intensity-fix on  (현 배치)
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_research.collect.naver_research_adapter import (
    build_naver_research_articles, save_adapted, adapted_path,
)
from market_research.analyze.news_classifier import classify_batch
from market_research.core.salience import (
    load_bm_anomaly_dates, RESEARCH_QUALITY_CAP,
    NEWS_UNCLASSIFIED_INTENSITY_FLOOR,
    TIER1_SOURCES, TIER2_SOURCES,
)

MONTH = '2026-01'
TOP_N_LIST = (50, 100, 200, 500)


def _source_quality(a: dict, use_cap: bool) -> float:
    if a.get('source_type') == 'naver_research':
        rqs = a.get('_research_quality_score')
        rqs_val = float(rqs) if rqs is not None else 0.7
        return min(rqs_val, RESEARCH_QUALITY_CAP) if use_cap else rqs_val
    src = a.get('source', '')
    if src in TIER1_SOURCES:
        return 1.0
    if src in TIER2_SOURCES:
        return 0.7
    return 0.3


def _salience(a: dict, bm_anomaly: set, use_cap: bool, use_intensity_fix: bool) -> float:
    sq = _source_quality(a, use_cap)
    intensity_norm = min(a.get('intensity', 0) / 10.0, 1.0)
    src_count = a.get('_event_source_count', 1)
    corroboration = min(src_count / 5.0, 1.0)
    art_date = a.get('date', '')[:10]
    bm_overlap = 1.0 if art_date in bm_anomaly else 0.0

    if use_intensity_fix:
        if (a.get('source_type') != 'naver_research'
                and not a.get('_classified_topics')
                and sq >= 0.7
                and (bm_overlap == 1.0 or src_count >= 3)):
            intensity_norm = max(intensity_norm, NEWS_UNCLASSIFIED_INTENSITY_FLOOR)

    return round(0.30 * sq + 0.25 * intensity_norm
                 + 0.25 * corroboration + 0.20 * bm_overlap, 3)


def _summarize(label: str, scored, total_news: int, total_nr: int):
    print(f'\n  === {label} ===')
    nr = [s for src, s in scored if src == 'naver_research']
    nws = [s for src, s in scored if src == 'news']
    print(f'  salience naver_research: mean={statistics.mean(nr):.3f}'
          f' median={statistics.median(nr):.3f} max={max(nr):.3f}')
    print(f'  salience news:           mean={statistics.mean(nws):.3f}'
          f' median={statistics.median(nws):.3f} max={max(nws):.3f}')
    scored.sort(key=lambda x: x[1], reverse=True)
    rows = []
    print(f'  | top N | naver_research | 비율 |')
    print(f'  |------:|---------------:|-----:|')
    for n in TOP_N_LIST:
        top = scored[:n]
        nrc = sum(1 for src, _ in top if src == 'naver_research')
        pct = nrc / max(len(top), 1) * 100
        rows.append((n, nrc, pct))
        print(f'  | {n:5d} | {nrc:14d} | {pct:5.1f}% |')
    return rows


def main() -> int:
    print(f'[setup] cap={RESEARCH_QUALITY_CAP}  intensity_floor={NEWS_UNCLASSIFIED_INTENSITY_FLOOR}')

    news_file = Path('market_research/data/news') / f'{MONTH}.json'
    news_articles = json.loads(news_file.read_text(encoding='utf-8')).get('articles', [])
    print(f'[load] news: {len(news_articles)}')

    nr_path = adapted_path(MONTH)
    if nr_path.exists():
        nr_articles = json.loads(nr_path.read_text(encoding='utf-8')).get('articles', [])
        already = sum(1 for a in nr_articles if a.get('_classified_topics') is not None)
        print(f'[load] naver_research adapted: {len(nr_articles)} (분류 캐시 {already})')
    else:
        nr_articles = build_naver_research_articles(MONTH)
        already = 0

    to_classify = [a for a in nr_articles if '_classified_topics' not in a]
    if to_classify:
        print(f'[classify] 미분류 {len(to_classify)}건')
        for i in range(0, len(to_classify), 30):
            classify_batch(to_classify[i:i+30])
        save_adapted(MONTH, nr_articles)

    y, m = int(MONTH[:4]), int(MONTH[5:7])
    try:
        bm_anomaly = load_bm_anomaly_dates(y, m)
    except Exception:
        bm_anomaly = set()
    print(f'[bm_anomaly] {len(bm_anomaly)}일')

    # intensity-fix 적용 후보 통계 (참고용)
    fix_candidates = sum(
        1 for a in news_articles
        if not a.get('_classified_topics')
        and a.get('source_type') != 'naver_research'
        and (a.get('source', '') in TIER1_SOURCES or a.get('source', '') in TIER2_SOURCES)
        and ((a.get('date', '')[:10] in bm_anomaly) or a.get('_event_source_count', 1) >= 3)
    )
    news_unclassified = sum(1 for a in news_articles if not a.get('_classified_topics'))
    print(f'[diag] news 미분류 {news_unclassified}건 중 intensity-fix 적용 후보 {fix_candidates}건')

    # 3가지 시나리오
    pre_raw = []
    post_cap = []
    post_cap_fix = []
    for a in news_articles:
        pre_raw.append(('news',           _salience(a, bm_anomaly, False, False)))
        post_cap.append(('news',          _salience(a, bm_anomaly, True,  False)))
        post_cap_fix.append(('news',      _salience(a, bm_anomaly, True,  True)))
    for a in nr_articles:
        pre_raw.append(('naver_research', _salience(a, bm_anomaly, False, False)))
        post_cap.append(('naver_research', _salience(a, bm_anomaly, True,  False)))
        post_cap_fix.append(('naver_research', _salience(a, bm_anomaly, True,  True)))

    print(f'\n[merged] total={len(pre_raw)}  baseline nr 비율: '
          f'{len(nr_articles)/(len(news_articles)+len(nr_articles))*100:.1f}%')

    _summarize('PRE_RAW       (cap off, fix off)',         pre_raw,      len(news_articles), len(nr_articles))
    _summarize('POST_CAP_ONLY (cap=0.70, fix off)',        post_cap,     len(news_articles), len(nr_articles))
    rows = _summarize('POST_CAP_FIX  (cap=0.70, fix on)',  post_cap_fix, len(news_articles), len(nr_articles))

    # 목표 판정
    targets = {50: (20, 70), 100: (20, 60), 200: None, 500: (20, 45)}
    print('\n  === 목표 범위 판정 (POST_CAP_FIX) ===')
    print('  | top N | 실측  | 목표      | 판정 |')
    print('  |------:|------:|:----------|:----:|')
    pass_count = eval_count = 0
    for n, _, pct in rows:
        rng = targets.get(n)
        if not rng:
            print(f'  | {n:5d} | {pct:5.1f}% | (목표 없음) | — |')
            continue
        eval_count += 1
        ok = rng[0] <= pct <= rng[1]
        if ok:
            pass_count += 1
        print(f'  | {n:5d} | {pct:5.1f}% | {rng[0]}~{rng[1]}% | {"✅" if ok else "❌"} |')
    print(f'\n  통과: {pass_count}/{eval_count}')
    print('  → Phase 3 진입 가능 ✅' if pass_count == eval_count
          else '  → 추가 보정 필요 ❌')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
