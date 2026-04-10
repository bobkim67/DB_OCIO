# -*- coding: utf-8 -*-
"""
Ablation Test — Upstream 정제 효과 비교
=======================================

4가지 조건에서 debate 컨텍스트 품질을 비교:
  A. baseline (정제 전: raw intensity 필터만)
  B. + dedupe (중복 제거)
  C. + dedupe + salience (이중 점수)
  D. + dedupe + salience + fallback (미분류 구제)

2펀드 × 2기간 × 4조건 = 16회 컨텍스트 빌드 → 비교 메트릭 출력.
LLM 호출 없이 컨텍스트 품질만 측정 (비용 $0).

사용법:
    python -m market_research.tests.ablation_test
    python -m market_research.tests.ablation_test --month 2026-03
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
NEWS_DIR = BASE_DIR / 'data' / 'news'


def load_articles(month_str: str) -> list[dict]:
    """월별 뉴스 JSON 로드."""
    f = NEWS_DIR / f'{month_str}.json'
    if not f.exists():
        print(f'  {f} 없음')
        return []
    data = json.loads(f.read_text(encoding='utf-8'))
    return data.get('articles', [])


def _metric_news_pool(articles: list[dict], condition: str) -> dict:
    """조건별 뉴스 풀 메트릭 계산."""
    classified = [a for a in articles if a.get('_classified_topics')]

    # 조건별 필터
    if condition == 'A_baseline':
        # 정제 전: intensity >= 7 (기존 debate 로직)
        pool = [a for a in classified if a.get('intensity', 0) >= 7]
    elif condition == 'B_dedupe':
        # + dedupe: primary만
        pool = [a for a in classified
                if a.get('is_primary', True) and a.get('intensity', 0) >= 7]
    elif condition == 'C_salience':
        # + salience: primary + salience 정렬
        primary = [a for a in classified if a.get('is_primary', True)]
        pool = sorted(primary,
                       key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)))
        pool = [a for a in pool if a.get('intensity', 0) >= 6][:15]
    elif condition == 'D_full':
        # 전체 정제: primary + salience + fallback 포함
        primary = [a for a in classified if a.get('is_primary', True)]
        pool = sorted(primary,
                       key=lambda x: (-x.get('_event_salience', 0), -x.get('intensity', 0)))
        pool = [a for a in pool if a.get('intensity', 0) >= 5][:20]
    else:
        pool = []

    # 메트릭 계산
    if not pool:
        return {'condition': condition, 'pool_size': 0}

    topics = Counter()
    sources = set()
    dates = set()
    avg_intensity = 0
    avg_salience = 0
    corroborated = 0  # event_source_count >= 2
    fallback_count = 0

    for a in pool:
        topics[a.get('primary_topic', '')] += 1
        sources.add(a.get('source', ''))
        dates.add(a.get('date', '')[:10])
        avg_intensity += a.get('intensity', 0)
        avg_salience += a.get('_event_salience', 0)
        if a.get('_event_source_count', 0) >= 2:
            corroborated += 1
        if a.get('_fallback_classified'):
            fallback_count += 1

    n = len(pool)
    return {
        'condition': condition,
        'pool_size': n,
        'unique_topics': len(topics),
        'top_topics': dict(topics.most_common(5)),
        'unique_sources': len(sources),
        'unique_dates': len(dates),
        'avg_intensity': round(avg_intensity / n, 2) if n else 0,
        'avg_salience': round(avg_salience / n, 3) if n else 0,
        'corroborated_pct': round(corroborated / n * 100, 1) if n else 0,
        'fallback_count': fallback_count,
    }


def run_ablation(month_str: str) -> list[dict]:
    """단일 월 ablation 실행."""
    articles = load_articles(month_str)
    if not articles:
        return []

    conditions = ['A_baseline', 'B_dedupe', 'C_salience', 'D_full']
    results = []
    for cond in conditions:
        m = _metric_news_pool(articles, cond)
        m['month'] = month_str
        results.append(m)

    return results


def print_comparison(results: list[dict]):
    """비교표 출력."""
    if not results:
        print('  결과 없음')
        return

    months = sorted(set(r['month'] for r in results))
    conditions = ['A_baseline', 'B_dedupe', 'C_salience', 'D_full']

    for month in months:
        print(f'\n{"="*70}')
        print(f'  {month} Ablation Results')
        print(f'{"="*70}')
        print(f'{"조건":<15} {"풀크기":>6} {"토픽수":>6} {"소스수":>6} '
              f'{"평균강도":>8} {"평균sal":>8} {"교차보도%":>9} {"fallback":>8}')
        print('-' * 70)

        for cond in conditions:
            r = next((x for x in results if x['month'] == month and x['condition'] == cond), None)
            if not r:
                continue
            print(f'{cond:<15} {r["pool_size"]:>6} {r.get("unique_topics",0):>6} '
                  f'{r.get("unique_sources",0):>6} {r.get("avg_intensity",0):>8.2f} '
                  f'{r.get("avg_salience",0):>8.3f} {r.get("corroborated_pct",0):>8.1f}% '
                  f'{r.get("fallback_count",0):>8}')

        # 개선 하이라이트
        baseline = next((x for x in results if x['month'] == month and x['condition'] == 'A_baseline'), None)
        full = next((x for x in results if x['month'] == month and x['condition'] == 'D_full'), None)
        if baseline and full and baseline['pool_size'] > 0:
            print(f'\n  개선 요약 (A→D):')
            size_delta = full['pool_size'] - baseline['pool_size']
            topic_delta = full.get('unique_topics', 0) - baseline.get('unique_topics', 0)
            print(f'    풀 크기: {baseline["pool_size"]} → {full["pool_size"]} ({size_delta:+d})')
            print(f'    토픽 다양성: {baseline.get("unique_topics",0)} → {full.get("unique_topics",0)} ({topic_delta:+d})')
            print(f'    교차보도: {baseline.get("corroborated_pct",0):.1f}% → {full.get("corroborated_pct",0):.1f}%')
            if full.get('fallback_count', 0):
                print(f'    미분류 구제: {full["fallback_count"]}건')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Ablation test for upstream refinement')
    parser.add_argument('--month', nargs='+', default=['2026-03', '2026-04'],
                        help='Target months (default: 2026-03 2026-04)')
    args = parser.parse_args()

    all_results = []
    for m in args.month:
        print(f'\n처리 중: {m}...')
        results = run_ablation(m)
        all_results.extend(results)

    print_comparison(all_results)

    # JSON 결과 저장
    out_file = BASE_DIR / 'data' / 'ablation_results.json'
    out_file.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n결과 저장: {out_file}')
