# -*- coding: utf-8 -*-
"""
Phase 2.5 Step 1 검증 — research-specific classifier 분기 분류율 비교.

naver_research_phase2.md §6.2 (30건 균등 샘플) 재현.
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_research.collect.naver_research_adapter import (
    build_naver_research_articles,
    CATEGORIES,
)
from market_research.analyze.news_classifier import classify_batch


MONTH = '2026-01'
PER_CAT = 6
SEED = 7  # phase2 보고와 동일 분포 재현 가능성을 위해 시드 고정


def main() -> int:
    rng = random.Random(SEED)
    articles = build_naver_research_articles(MONTH)
    print(f'[load] {MONTH}: total={len(articles)}')

    by_cat: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
    for a in articles:
        cat = a.get('_raw_category')
        if cat in by_cat:
            by_cat[cat].append(a)

    sample: list[dict] = []
    for cat in CATEGORIES:
        pool = by_cat[cat]
        rng.shuffle(pool)
        sample.extend(pool[:PER_CAT])

    print(f'[sample] n={len(sample)} (per_cat={PER_CAT})')

    # classify (research bucket로 라우팅 됨 — source_type='naver_research')
    classify_batch(sample)

    # 결과 집계
    classified = [a for a in sample if a.get('_classified_topics')]
    primary = Counter(a.get('primary_topic') for a in classified)
    by_cat_rate: dict[str, list[int]] = {c: [0, 0] for c in CATEGORIES}  # [classified, total]
    for a in sample:
        cat = a.get('_raw_category')
        by_cat_rate[cat][1] += 1
        if a.get('_classified_topics'):
            by_cat_rate[cat][0] += 1

    print()
    print(f'분류 성공: {len(classified)}/{len(sample)} ({len(classified)/len(sample)*100:.1f}%)')
    print('primary_topic 분포:')
    for k, v in primary.most_common():
        print(f'  {k}: {v}')
    print('카테고리별 분류율:')
    for c, (ok, tot) in by_cat_rate.items():
        print(f'  {c:12s}: {ok}/{tot} ({(ok/tot*100) if tot else 0:.0f}%)')

    print()
    print('상세 (분류된 기사):')
    for a in classified:
        cat = a.get('_raw_category')
        title = (a.get('title') or '')[:80]
        topics = ', '.join(t['topic'] for t in a['_classified_topics'])
        print(f'  [{cat}] {title} → {topics}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
