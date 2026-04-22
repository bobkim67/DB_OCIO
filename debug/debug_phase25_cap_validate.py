# -*- coding: utf-8 -*-
"""
Phase 2.5 후속 (Option A) cap 적용 후 재측정.

비교 대상:
  - PRE  : RESEARCH_QUALITY_CAP 적용 안 한 것처럼 source_quality = _research_quality_score
  - POST : RESEARCH_QUALITY_CAP=0.85 적용 (현재 salience.py 상태)

전제: adapter가 이미 빌드되어 있고 분류 결과를 캐시 (_classified_topics 보존).
2026-01 raw에서 빌드 → 한 번만 분류 → cap-on/off 두 가지로 salience 재계산.
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
    compute_event_salience, compute_salience_batch, load_bm_anomaly_dates,
    TIER1_SOURCES, TIER2_SOURCES, RESEARCH_QUALITY_CAP,
)

MONTH = '2026-01'
TOP_N_LIST = (50, 100, 200, 500)


def _force_source_quality(a: dict, use_cap: bool) -> float:
    """compute_event_salience 의 source_quality 슬롯만 재현."""
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


def _recalc_salience(a: dict, bm_anomaly: set, use_cap: bool) -> float:
    sq = _force_source_quality(a, use_cap)
    intensity_norm = min(a.get('intensity', 0) / 10.0, 1.0)
    src_count = a.get('_event_source_count', 1)
    corroboration = min(src_count / 5.0, 1.0)
    art_date = a.get('date', '')[:10]
    bm_overlap = 1.0 if art_date in bm_anomaly else 0.0
    score = (0.30 * sq + 0.25 * intensity_norm
             + 0.25 * corroboration + 0.20 * bm_overlap)
    return round(score, 3)


def _summarize(label: str, merged_with_score, total_nr, total_news):
    print(f'\n  === {label} ===')
    nr_sals = [s for src, s in merged_with_score if src == 'naver_research']
    news_sals = [s for src, s in merged_with_score if src == 'news']
    print(f'  salience naver_research: mean={statistics.mean(nr_sals):.3f}'
          f' median={statistics.median(nr_sals):.3f} max={max(nr_sals):.3f}')
    print(f'  salience news:           mean={statistics.mean(news_sals):.3f}'
          f' median={statistics.median(news_sals):.3f} max={max(news_sals):.3f}')

    merged_with_score.sort(key=lambda x: x[1], reverse=True)
    print(f'\n  | top N | naver_research | 비율 |')
    print(f'  |------:|---------------:|-----:|')
    rows = []
    for n in TOP_N_LIST:
        top = merged_with_score[:n]
        nr = sum(1 for src, _ in top if src == 'naver_research')
        pct = nr / max(len(top), 1) * 100
        rows.append((n, nr, pct))
        print(f'  | {n:5d} | {nr:14d} | {pct:5.1f}% |')
    return rows


def main() -> int:
    print(f'[setup] cap = {RESEARCH_QUALITY_CAP}')

    # 1) news 로드
    news_file = Path('market_research/data/news') / f'{MONTH}.json'
    news_data = json.loads(news_file.read_text(encoding='utf-8'))
    news_articles = news_data.get('articles', [])
    print(f'[load] news: {len(news_articles)}')

    # 2) naver_research adapted 로드 (이전 검증 batch에서 생성된 분류 결과 재사용)
    nr_path = adapted_path(MONTH)
    if nr_path.exists():
        nr_data = json.loads(nr_path.read_text(encoding='utf-8'))
        nr_articles = nr_data.get('articles', [])
        already = sum(1 for a in nr_articles if a.get('_classified_topics') is not None)
        print(f'[load] naver_research adapted: {len(nr_articles)} (분류 캐시: {already})')
    else:
        nr_articles = build_naver_research_articles(MONTH)
        already = 0
        print(f'[load] naver_research (raw build): {len(nr_articles)} (분류 캐시 없음)')

    # 3) 미분류만 분류
    to_classify = [a for a in nr_articles if '_classified_topics' not in a]
    if to_classify:
        print(f'[classify] 미분류 {len(to_classify)}건 분류 중 (배치 30)')
        BATCH = 30
        for i in range(0, len(to_classify), BATCH):
            classify_batch(to_classify[i:i + BATCH])
        # 캐시 저장 (다음 회차 빠르게)
        save_adapted(MONTH, nr_articles)
    else:
        print(f'[classify] 전부 분류 캐시 사용 — LLM 호출 없음')

    # 4) BM anomaly
    y, m = int(MONTH[:4]), int(MONTH[5:7])
    try:
        bm_anomaly = load_bm_anomaly_dates(y, m)
    except Exception:
        bm_anomaly = set()
    print(f'[bm_anomaly] {len(bm_anomaly)}일')

    # 5) PRE / POST 두 가지 salience 동시 계산 (같은 분류 결과 위에서)
    pre = []
    post = []
    for a in news_articles:
        sp = _recalc_salience(a, bm_anomaly, use_cap=False)
        sq = _recalc_salience(a, bm_anomaly, use_cap=True)
        pre.append(('news', sp))
        post.append(('news', sq))
    for a in nr_articles:
        sp = _recalc_salience(a, bm_anomaly, use_cap=False)
        sq = _recalc_salience(a, bm_anomaly, use_cap=True)
        pre.append(('naver_research', sp))
        post.append(('naver_research', sq))

    print(f'\n[merged] total={len(pre)} (news {len(news_articles)} + nr {len(nr_articles)})')
    base_pct = len(nr_articles) / max(len(pre), 1) * 100
    print(f'  baseline naver_research 비율: {base_pct:.1f}%')

    pre_rows = _summarize('PRE  (cap 미적용)', pre, len(nr_articles), len(news_articles))
    post_rows = _summarize('POST (cap=0.85)',  post, len(nr_articles), len(news_articles))

    # 6) 목표 범위 판정
    targets = {50: (20, 70), 100: (20, 60), 200: None, 500: (20, 45)}
    print('\n  === 목표 범위 판정 (POST) ===')
    print('  | top N | 실측 | 목표  | 판정 |')
    print('  |------:|-----:|:------|:-----|')
    pass_count = 0
    eval_count = 0
    for n, _, pct in post_rows:
        rng = targets.get(n)
        if not rng:
            print(f'  | {n:5d} | {pct:5.1f}% | (목표 없음) | — |')
            continue
        eval_count += 1
        ok = rng[0] <= pct <= rng[1]
        if ok:
            pass_count += 1
        verdict = '✅' if ok else '❌'
        print(f'  | {n:5d} | {pct:5.1f}% | {rng[0]}~{rng[1]}% | {verdict} |')
    print(f'\n  통과: {pass_count}/{eval_count}')
    if pass_count == eval_count:
        print('  → Phase 3 진입 가능 ✅')
    else:
        print('  → 추가 보정 필요 ❌')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
