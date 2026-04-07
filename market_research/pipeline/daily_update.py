# -*- coding: utf-8 -*-
"""
Daily Incremental Update — MTD/YTD 일일 시황 업데이트
=====================================================

Phase 1.5: 월초 Full Build 기저 대비 일일 변화 추적.

파이프라인:
  1. 당일 뉴스 수집 (네이버 금융)
  2. 당일 뉴스 분류 (Haiku, 21개 주제)
  3. GraphRAG 증분 엣지 추가
  4. 기저 대비 델타 요약 (MTD topic shift)
  5. regime_memory 업데이트
  6. daily/{MM-DD}.json 저장

사용법:
    python -m market_research.daily_update                # 오늘
    python -m market_research.daily_update 2026-04-03     # 특정일
    python -m market_research.daily_update --dry-run      # 수집/분류만 (LLM 없이)

비용: ~$0.035/일 (분류 ~$0.02 + GraphRAG 증분 ~$0.015)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent  # market_research/
DATA_DIR = BASE_DIR / 'data'
NEWS_DIR = DATA_DIR / 'news'
CACHE_DIR = DATA_DIR / 'report_cache'
REGIME_FILE = DATA_DIR / 'regime_memory.json'


def daily_update(date_str: str = None, dry_run: bool = False) -> dict:
    """
    일일 증분 업데이트 메인 함수.

    Parameters
    ----------
    date_str : str, optional
        대상 날짜 (YYYY-MM-DD). None이면 오늘.
    dry_run : bool
        True면 뉴스 수집/분류만 (GraphRAG/델타 생략)

    Returns
    -------
    dict : 실행 결과 요약
    """
    if date_str is None:
        date_str = date.today().isoformat()

    year, month, day = int(date_str[:4]), int(date_str[5:7]), int(date_str[8:10])
    month_str = f'{year}-{month:02d}'
    day_str = f'{month:02d}-{day:02d}'

    print(f'\n{"="*60}')
    print(f'  Daily Update: {date_str}')
    print(f'{"="*60}')

    result = {
        'date': date_str,
        'started_at': datetime.now().isoformat(),
        'steps': {},
    }

    # ── Step 1: 뉴스 수집 ──
    print(f'\n[Step 1] 뉴스 수집...')
    news_result = _step_collect_news(date_str)
    result['steps']['collect'] = news_result
    print(f'  → {news_result.get("new_count", 0)}건 신규')

    # ── Step 2: 뉴스 분류 ──
    print(f'\n[Step 2] 뉴스 분류...')
    classify_result = _step_classify(date_str)
    result['steps']['classify'] = classify_result
    print(f'  → {classify_result.get("classified", 0)}/{classify_result.get("total", 0)}건')

    if dry_run:
        print(f'\n  [dry-run] GraphRAG/델타 생략')
        result['dry_run'] = True
        _save_daily_cache(month_str, day_str, result)
        return result

    # ── Step 3: GraphRAG 증분 ──
    print(f'\n[Step 3] GraphRAG 증분...')
    graph_result = _step_graph_incremental(year, month, date_str)
    result['steps']['graph'] = graph_result
    print(f'  → 노드 {graph_result.get("node_count", 0)}, 엣지 {graph_result.get("edge_count", 0)}')

    # ── Step 4: MTD 델타 요약 ──
    print(f'\n[Step 4] MTD 델타 요약...')
    delta = _step_mtd_delta(year, month, date_str)
    result['steps']['delta'] = delta
    print(f'  → 토픽 {len(delta.get("topic_counts", {}))}개, 방향성 {delta.get("sentiment", "N/A")}')

    # ── Step 5: regime_memory 업데이트 ──
    print(f'\n[Step 5] regime_memory 체크...')
    regime = _step_regime_check(delta)
    result['steps']['regime'] = regime

    result['completed_at'] = datetime.now().isoformat()

    # ── 저장 ──
    _save_daily_cache(month_str, day_str, result)

    print(f'\n{"="*60}')
    print(f'  완료: {result["completed_at"]}')
    print(f'{"="*60}\n')

    return result


# ═══════════════════════════════════════════════════════
# Step 구현
# ═══════════════════════════════════════════════════════

def _step_collect_news(date_str: str) -> dict:
    """Step 1: 네이버 금융 + Finnhub 뉴스 수집"""
    total_new = 0

    # 1a. 네이버 금융
    try:
        from market_research.collect.macro_data import load_naver_finance_news
        naver = load_naver_finance_news()
        naver_today = sum(1 for a in naver if a.get('date', '') == date_str)
        total_new += naver_today
        print(f'  네이버: {naver_today}건')
    except Exception as exc:
        print(f'  네이버 수집 실패: {exc}')

    # 1b. Finnhub (영문 — 해외 시황 보강)
    try:
        from market_research.collect.macro_data import load_finnhub_news
        finnhub = load_finnhub_news(from_date=date_str, to_date=date_str)
        finnhub_today = sum(1 for a in finnhub if a.get('date', '') == date_str)
        total_new += finnhub_today
        print(f'  Finnhub: {finnhub_today}건')
    except Exception as exc:
        print(f'  Finnhub 수집 실패: {exc}')

    return {'status': 'ok', 'new_count': total_new}


def _step_classify(date_str: str) -> dict:
    """Step 2: 당일 뉴스 분류"""
    try:
        from market_research.analyze.news_classifier import classify_daily
        return classify_daily(date_str)
    except Exception as exc:
        print(f'  분류 실패: {exc}')
        return {'status': 'error', 'error': str(exc), 'total': 0, 'classified': 0}


def _step_graph_incremental(year: int, month: int, date_str: str) -> dict:
    """Step 3: GraphRAG 증분 엣지 추가"""
    try:
        from market_research.analyze.graph_rag import add_incremental_edges

        # 당일 분류 완료된 기사 로드
        month_str = f'{year}-{month:02d}'
        news_file = NEWS_DIR / f'{month_str}.json'
        if not news_file.exists():
            return {'status': 'skip', 'reason': 'no news file'}

        data = json.loads(news_file.read_text(encoding='utf-8'))
        daily_articles = [
            a for a in data.get('articles', [])
            if a.get('date', '') == date_str and '_classified_topics' in a
        ]

        if not daily_articles:
            return {'status': 'skip', 'reason': 'no classified articles'}

        graph = add_incremental_edges(year, month, daily_articles)
        return {
            'status': 'ok',
            'articles_used': len(daily_articles),
            'node_count': len(graph.get('nodes', {})),
            'edge_count': len(graph.get('edges', [])),
        }
    except Exception as exc:
        print(f'  GraphRAG 실패: {exc}')
        return {'status': 'error', 'error': str(exc), 'node_count': 0, 'edge_count': 0}


def _step_mtd_delta(year: int, month: int, date_str: str) -> dict:
    """
    Step 4: MTD 델타 — 월초 Full Build 기저 대비 변화.
    LLM 불필요 (토픽 카운트 + 방향성 집계).
    """
    month_str = f'{year}-{month:02d}'
    news_file = NEWS_DIR / f'{month_str}.json'
    if not news_file.exists():
        return {'status': 'skip', 'topic_counts': {}, 'sentiment': 'N/A'}

    data = json.loads(news_file.read_text(encoding='utf-8'))
    articles = data.get('articles', [])

    # MTD: 월초~date_str까지 분류된 기사
    mtd_articles = [
        a for a in articles
        if a.get('date', '') <= date_str and '_classified_topics' in a
    ]

    # 토픽 카운트 + 방향성 집계
    topic_counts = {}
    topic_direction = {}  # topic → {positive: n, negative: n, neutral: n}
    asset_impact_agg = {}  # asset → sum

    for article in mtd_articles:
        topics = article.get('_classified_topics', [])
        for t in topics:
            name = t.get('topic', '')
            if not name:
                continue
            topic_counts[name] = topic_counts.get(name, 0) + 1
            direction = t.get('direction', 'neutral')
            if name not in topic_direction:
                topic_direction[name] = {'positive': 0, 'negative': 0, 'neutral': 0}
            topic_direction[name][direction] = topic_direction[name].get(direction, 0) + 1

        impact = article.get('_asset_impact_vector', {})
        for asset, score in impact.items():
            asset_impact_agg[asset] = asset_impact_agg.get(asset, 0) + score

    # 전체 방향성 요약
    total_pos = sum(d.get('positive', 0) for d in topic_direction.values())
    total_neg = sum(d.get('negative', 0) for d in topic_direction.values())
    if total_pos > total_neg * 1.3:
        sentiment = 'positive'
    elif total_neg > total_pos * 1.3:
        sentiment = 'negative'
    else:
        sentiment = 'mixed'

    # 상위 5개 토픽
    top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        'status': 'ok',
        'mtd_articles': len(mtd_articles),
        'topic_counts': dict(top_topics),
        'topic_direction': topic_direction,
        'asset_impact': asset_impact_agg,
        'sentiment': sentiment,
        'positive_count': total_pos,
        'negative_count': total_neg,
    }


def _step_regime_check(delta: dict) -> dict:
    """
    Step 5: regime_memory 업데이트 + regime shift 자동 감지.

    감지 룰 (LLM 불필요):
      - 상위 토픽이 현재 narrative 키워드와 50% 이상 불일치 → shift 후보
      - sentiment가 현재 regime 방향과 반대 → shift 후보
      - shift 후보가 3일 연속 → shift 확정
    """
    if not REGIME_FILE.exists():
        return {'status': 'skip', 'reason': 'no regime_memory'}

    regime = json.loads(REGIME_FILE.read_text(encoding='utf-8'))
    current = regime.get('current', {})
    narrative = current.get('dominant_narrative', '')

    # ── shift 감지 ──
    shift_detected = False
    shift_reason = ''
    top_topics = list(delta.get('topic_counts', {}).keys())

    if narrative and top_topics:
        # 현재 narrative에서 키워드 추출
        narrative_keywords = set(narrative.replace('+', ' ').replace(',', ' ').split())
        # 상위 토픽과 교집합
        overlap = sum(1 for t in top_topics if any(kw in t for kw in narrative_keywords))
        overlap_ratio = overlap / len(top_topics) if top_topics else 1.0

        if overlap_ratio < 0.3:
            shift_detected = True
            shift_reason = f'토픽 불일치 {1-overlap_ratio:.0%} (상위: {", ".join(top_topics[:3])})'

    # shift 연속일 카운트
    consecutive = regime.get('_shift_consecutive_days', 0)
    if shift_detected:
        consecutive += 1
    else:
        consecutive = 0
    regime['_shift_consecutive_days'] = consecutive

    # 3일 연속 shift → 확정
    if consecutive >= 3:
        new_narrative = ' + '.join(top_topics[:3])
        old = current.copy()
        regime.setdefault('history', []).append({
            'narrative': narrative,
            'period': f'{current.get("since", "?")} ~ {date.today().isoformat()}',
        })
        regime['previous'] = {
            'dominant_narrative': narrative,
            'ended': date.today().isoformat(),
        }
        regime['current'] = {
            'dominant_narrative': new_narrative,
            'weeks': 0,
            'since': date.today().isoformat(),
        }
        regime['shift_detected'] = True
        regime['shift_description'] = f'{narrative} → {new_narrative}'
        regime['_shift_consecutive_days'] = 0
        shift_reason = f'3일 연속 토픽 변화 → regime 전환: {new_narrative}'
        print(f'  ⚠ Regime shift 감지: {shift_reason}')
    else:
        regime['shift_detected'] = False

    regime['last_daily_update'] = date.today().isoformat()
    REGIME_FILE.write_text(json.dumps(regime, ensure_ascii=False, indent=2), encoding='utf-8')

    return {
        'status': 'ok',
        'current_narrative': regime['current'].get('dominant_narrative', ''),
        'weeks': regime['current'].get('weeks', 0),
        'shift_consecutive_days': consecutive,
        'shift_reason': shift_reason if shift_detected else '',
    }


# ═══════════════════════════════════════════════════════
# 캐시 저장
# ═══════════════════════════════════════════════════════

def _save_daily_cache(month_str: str, day_str: str, result: dict):
    """daily/{MM-DD}.json 저장"""
    daily_dir = CACHE_DIR / month_str / 'daily'
    daily_dir.mkdir(parents=True, exist_ok=True)
    out_file = daily_dir / f'{day_str}.json'
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'  [저장] {out_file}')


# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Daily incremental update')
    parser.add_argument('date', nargs='?', default=None,
                        help='Target date (YYYY-MM-DD). Default: today')
    parser.add_argument('--dry-run', action='store_true',
                        help='Collect/classify only (no GraphRAG)')
    args = parser.parse_args()
    daily_update(args.date, dry_run=args.dry_run)
