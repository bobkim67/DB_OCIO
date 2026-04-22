# -*- coding: utf-8 -*-
"""
Phase 2.5 Step 2 검증 — 두 부분으로 구성:

(a) 2026-02 smoke test (15건 균등 = 카테고리당 3건)
    → empty topic 비율 / article당 평균 topic 수 / primary_topic 쏠림 확인.

(b) 상위 500 evidence 중 naver_research 비율 (2026-01)
    → baseline 21.1% 대비 30%(>=6.3%) 통과 여부.
    Phase 2 보고서 §6.3과 동일한 방법으로 비교.
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_research.collect.naver_research_adapter import (
    build_naver_research_articles,
    save_adapted,
    adapted_path,
    CATEGORIES,
)
from market_research.analyze.news_classifier import classify_batch
from market_research.core.salience import (
    compute_salience_batch, load_bm_anomaly_dates,
)


def smoke_test(month: str, per_cat: int = 3, seed: int = 11):
    print(f'\n=== (a) Smoke test {month} (per_cat={per_cat}) ===')
    rng = random.Random(seed)
    articles = build_naver_research_articles(month)
    print(f'  load {month}: total={len(articles)}')
    by_cat = {c: [] for c in CATEGORIES}
    for a in articles:
        by_cat.get(a.get('_raw_category'), []).append(a)
    sample = []
    for cat in CATEGORIES:
        rng.shuffle(by_cat[cat])
        sample.extend(by_cat[cat][:per_cat])
    print(f'  sample n={len(sample)}')

    classify_batch(sample)

    classified = [a for a in sample if a.get('_classified_topics')]
    topic_counts = [len(a.get('_classified_topics', [])) for a in sample]
    primary = Counter(a.get('primary_topic') for a in classified)
    empty_pct = (len(sample) - len(classified)) / len(sample) * 100
    avg_topics = sum(topic_counts) / max(len(sample), 1)

    print(f'  empty topic 비율: {empty_pct:.1f}%')
    print(f'  article당 평균 topic 수: {avg_topics:.2f}')
    print(f'  primary_topic 분포 (top5):')
    for k, v in primary.most_common(5):
        pct = v / max(len(classified), 1) * 100
        print(f'    {k}: {v} ({pct:.0f}%)')
    if primary:
        max_share = primary.most_common(1)[0][1] / max(len(classified), 1)
        flag = ' ⚠️ 과쏠림' if max_share >= 0.5 else ''
        print(f'  최고 토픽 점유율: {max_share*100:.0f}%{flag}')


def evidence_ratio(month: str, top_n_list=(50, 100, 200, 500)):
    print(f'\n=== (b) Evidence ratio {month} ===')

    # news 로드
    news_file = Path('market_research/data/news') / f'{month}.json'
    if news_file.exists():
        news_data = json.loads(news_file.read_text(encoding='utf-8'))
        news_articles = news_data.get('articles', [])
    else:
        news_articles = []
    print(f'  news: {len(news_articles)}')

    # naver_research adapted 로드 (이미 분류·정제됐다는 보장은 없음 — refine 다시 한번)
    nr_articles = build_naver_research_articles(month)
    print(f'  naver_research (adapted from raw): {len(nr_articles)}')

    # naver_research 분류 (배치 단위) — 비용 절감 위해 80개씩
    print('  naver_research 분류 중 (배치)...')
    BATCH = 30
    for i in range(0, len(nr_articles), BATCH):
        batch = nr_articles[i:i + BATCH]
        classify_batch(batch)
        print(f'    batch {i//BATCH + 1}/{(len(nr_articles) + BATCH - 1)//BATCH} done', end='\r', flush=True)
    print()

    # BM anomaly
    y, m = int(month[:4]), int(month[5:7])
    try:
        bm_anomaly = load_bm_anomaly_dates(y, m)
    except Exception:
        bm_anomaly = set()
    print(f'  BM anomaly: {len(bm_anomaly)}일')

    # salience 적용 (두 소스에 동일하게)
    compute_salience_batch(news_articles, bm_anomaly)
    compute_salience_batch(nr_articles, bm_anomaly)

    merged = []
    for a in news_articles:
        merged.append(('news', a))
    for a in nr_articles:
        merged.append(('naver_research', a))
    merged.sort(key=lambda x: x[1].get('_event_salience', 0), reverse=True)

    print(f'  total merged: {len(merged)}')
    base_pct = sum(1 for s, _ in merged if s == 'naver_research') / max(len(merged), 1) * 100
    print(f'  baseline naver_research 비율: {base_pct:.1f}%')
    threshold_pct = base_pct * 0.30
    print(f'  통과 기준 (>= baseline*30%): {threshold_pct:.2f}%')

    print(f'\n  | top N | naver_research | 비율 | 판정 |')
    print(f'  |------:|---------------:|-----:|-----|')
    pass_count = 0
    for n in top_n_list:
        top = merged[:n]
        nr_count = sum(1 for s, _ in top if s == 'naver_research')
        pct = nr_count / max(len(top), 1) * 100
        ok = '✅' if pct >= threshold_pct else '❌'
        if pct >= threshold_pct:
            pass_count += 1
        print(f'  | {n:5d} | {nr_count:14d} | {pct:5.1f}% | {ok} |')

    # salience 분포
    nr_sals = [a.get('_event_salience', 0) for s, a in merged if s == 'naver_research']
    news_sals = [a.get('_event_salience', 0) for s, a in merged if s == 'news']
    if nr_sals and news_sals:
        import statistics
        print(f'\n  salience (naver_research): mean={statistics.mean(nr_sals):.3f}'
              f' median={statistics.median(nr_sals):.3f} max={max(nr_sals):.3f}')
        print(f'  salience (news):            mean={statistics.mean(news_sals):.3f}'
              f' median={statistics.median(news_sals):.3f} max={max(news_sals):.3f}')

    # 최종 평가
    if pass_count == len(top_n_list):
        print(f'\n  결과: 모든 top N에서 통과 ✅')
    else:
        print(f'\n  결과: {pass_count}/{len(top_n_list)} 통과')


def main() -> int:
    smoke_test('2026-02', per_cat=3, seed=11)
    evidence_ratio('2026-01')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
