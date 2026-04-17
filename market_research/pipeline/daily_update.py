# -*- coding: utf-8 -*-
"""
Daily Incremental Update — MTD/YTD 일일 시황 업데이트
=====================================================

Phase 1.5: 월초 Full Build 기저 대비 일일 변화 추적.

파이프라인:
  0. 매크로 지표 수집 (SCIP/FRED/NYFed/ECOS)
  1. 뉴스 수집 (네이버 + Finnhub + NewsAPI)
  1.5. 블로그 수집 (monygeek, Selenium 증분)
  1.6. 블로그 인사이트 빌드 (Haiku 인과분석, 매 실행 시 재빌드)
  2. 뉴스 분류 (Haiku, 14개 토픽)
  2.5. 정제 (dedupe + salience + fallback)
  3. GraphRAG 증분 엣지 추가
  4. MTD 델타 요약 (토픽 카운트)
  5. regime_memory 업데이트

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

    # ── Step 0: 매크로 지표 수집 ──
    print(f'\n[Step 0] 매크로 지표 수집...')
    macro_result = _step_collect_macro()
    result['steps']['macro'] = macro_result

    # ── Step 1: 뉴스 수집 ──
    print(f'\n[Step 1] 뉴스 수집...')
    news_result = _step_collect_news(date_str)
    result['steps']['collect'] = news_result
    print(f'  → {news_result.get("new_count", 0)}건 신규')

    # ── Step 1.5: 블로그 수집 ──
    print(f'\n[Step 1.5] 블로그 수집...')
    blog_result = _step_collect_blog()
    result['steps']['blog'] = blog_result

    # ── Step 1.6: 블로그 인사이트 빌드 ──
    print(f'\n[Step 1.6] 블로그 인사이트 빌드...')
    blog_insight_result = _step_blog_insight(year, month)
    result['steps']['blog_insight'] = blog_insight_result

    # ── Step 2: 뉴스 분류 ──
    print(f'\n[Step 2] 뉴스 분류...')
    classify_result = _step_classify(date_str)
    result['steps']['classify'] = classify_result
    print(f'  → {classify_result.get("classified", 0)}/{classify_result.get("total", 0)}건')

    # ── Step 2.5: Dedupe + Salience + Uncategorized Fallback ──
    print(f'\n[Step 2.5] Dedupe + Salience + Fallback...')
    refine_result = _step_refine(month_str)
    result['steps']['refine'] = refine_result
    print(f'  → dedup그룹 {refine_result.get("dedup_groups", 0)}, '
          f'이벤트그룹 {refine_result.get("event_groups", 0)}, '
          f'fallback {refine_result.get("fallback_count", 0)}건')

    # ── Step 2.6: Base wiki pages (event/entity/asset/fund) ──
    # canonical regime / debate narrative / graph transmission path 포함 금지.
    print(f'\n[Step 2.6] Base wiki pages...')
    try:
        from market_research.wiki.draft_pages import refresh_base_pages_after_refine
        wiki_result = refresh_base_pages_after_refine(month_str)
        result['steps']['wiki_base'] = wiki_result
        print(f'  → events {wiki_result["events"]}, entities {wiki_result["entities"]}, '
              f'assets {wiki_result["assets"]}, funds {wiki_result["funds"]}')
    except Exception as exc:
        print(f'  Base wiki 생성 실패: {exc}')
        result['steps']['wiki_base'] = {'status': 'error', 'error': str(exc)}

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

def _step_collect_macro() -> dict:
    """Step 0: SCIP/FRED/NYFed/ECOS 매크로 지표 수집"""
    try:
        from market_research.collect.macro_data import run as macro_run
        macro_run()
        return {'status': 'ok'}
    except Exception as exc:
        print(f'  매크로 지표 수집 실패: {exc}')
        return {'status': 'error', 'error': str(exc)}


def _step_collect_blog() -> dict:
    """Step 1.5: monygeek 블로그 증분 수집 (Selenium)"""
    try:
        from market_research.collect.naver_blog import run as blog_run, load_existing_posts
        before = len(load_existing_posts())
        blog_run(incremental=True)
        after = len(load_existing_posts())
        new_count = after - before
        print(f'  블로그: {before} → {after}건 (신규 {new_count}건)')
        return {'status': 'ok', 'before': before, 'after': after, 'new_count': new_count}
    except Exception as exc:
        print(f'  블로그 수집 실패: {exc}')
        return {'status': 'error', 'error': str(exc)}


def _step_blog_insight(year: int, month: int) -> dict:
    """Step 1.6: 블로그 인사이트 빌드 (수집할 때마다 재빌드)"""
    try:
        from market_research.analyze.blog_analyst import build_blog_insight
        result = build_blog_insight(year, month)
        post_count = result.get('summary', {}).get('post_count', 0)
        edge_count = result.get('summary', {}).get('total_edges', 0)
        print(f'  → 포스트 {post_count}건, 엣지 {edge_count}개')
        return {'status': 'ok', 'post_count': post_count, 'edge_count': edge_count}
    except Exception as exc:
        print(f'  블로그 인사이트 빌드 실패: {exc}')
        return {'status': 'error', 'error': str(exc)}


def _step_collect_news(date_str: str) -> dict:
    """Step 1: 네이버 + Finnhub + NewsAPI 뉴스 수집 (load_news_all 통합 호출)"""
    try:
        from market_research.collect.macro_data import load_news_all
        load_news_all()
        return {'status': 'ok'}
    except Exception as exc:
        print(f'  뉴스 수집 실패: {exc}')
        return {'status': 'error', 'error': str(exc)}


def _step_classify(date_str: str) -> dict:
    """Step 2: 당일 뉴스 분류"""
    try:
        from market_research.analyze.news_classifier import classify_daily
        return classify_daily(date_str)
    except Exception as exc:
        print(f'  분류 실패: {exc}')
        return {'status': 'error', 'error': str(exc), 'total': 0, 'classified': 0}


def _step_refine(month_str: str) -> dict:
    """Step 2.5: 월별 뉴스 전체에 dedupe + salience + uncategorized fallback 적용."""
    try:
        from market_research.core.dedupe import process_dedupe_and_events
        from market_research.core.salience import (
            compute_salience_batch, fallback_classify_uncategorized, load_bm_anomaly_dates)
        from market_research.core.json_utils import safe_read_news_json, safe_write_news_json

        news_file = NEWS_DIR / f'{month_str}.json'
        if not news_file.exists():
            return {'status': 'skip', 'reason': 'no news file'}

        # 전체 데이터 로드 (메타 보존)
        raw_data = json.loads(news_file.read_text(encoding='utf-8'))
        articles = raw_data.get('articles', [])
        if not articles:
            return {'status': 'skip', 'reason': 'no articles'}

        # BM anomaly dates 로드 (z>1.5)
        y, m = int(month_str[:4]), int(month_str[5:7])
        try:
            bm_anomaly = load_bm_anomaly_dates(y, m)
            print(f'  BM anomaly dates: {len(bm_anomaly)}일')
        except Exception as exc:
            print(f'  BM anomaly 로드 실패: {exc}')
            bm_anomaly = set()

        # A. article_id + dedupe + event clustering
        articles = process_dedupe_and_events(articles)

        # B. salience 점수 (bm_anomaly_dates 연동)
        articles = compute_salience_batch(articles, bm_anomaly)

        # C. uncategorized fallback
        fallback_count = fallback_classify_uncategorized(articles, bm_anomaly)

        # 통계 집계
        dedup_groups = len({a.get('_dedup_group_id') for a in articles if '_dedup_group_id' in a})
        primary_count = sum(1 for a in articles if a.get('is_primary', False))
        event_groups = len({a.get('_event_group_id') for a in articles if '_event_group_id' in a})

        # 저장
        raw_data['articles'] = articles
        safe_write_news_json(news_file, raw_data)

        return {
            'status': 'ok',
            'total': len(articles),
            'primary_count': primary_count,
            'dedup_groups': dedup_groups,
            'event_groups': event_groups,
            'fallback_count': fallback_count,
        }
    except Exception as exc:
        print(f'  Refine 실패: {exc}')
        import traceback; traceback.print_exc()
        return {'status': 'error', 'error': str(exc),
                'dedup_groups': 0, 'event_groups': 0, 'fallback_count': 0}


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


def _compute_delta_from_articles(articles: list[dict],
                                  asof_date: date | None = None) -> dict:
    """Pure function — articles → delta dict (topic_counts + sentiment +
    topic_direction + asset_impact).

    No file I/O. Caller is responsible for filtering `articles` to the
    intended date range before calling (live uses MTD cutoff; replay uses
    as-of-date rolling window). Articles must already carry
    `_classified_topics` and `_asset_impact_vector` from the classifier
    step — that upstream output is treated as input here.
    """
    topic_counts: dict[str, int] = {}
    topic_direction: dict[str, dict] = {}
    asset_impact_agg: dict[str, float] = {}

    for article in articles:
        topics = article.get('_classified_topics', [])
        for t in topics:
            name = t.get('topic', '')
            if not name:
                continue
            topic_counts[name] = topic_counts.get(name, 0) + 1
            direction = t.get('direction', 'neutral')
            if name not in topic_direction:
                topic_direction[name] = {'positive': 0, 'negative': 0, 'neutral': 0}
            topic_direction[name][direction] = (
                topic_direction[name].get(direction, 0) + 1
            )
        impact = article.get('_asset_impact_vector', {}) or {}
        for asset, score in impact.items():
            asset_impact_agg[asset] = asset_impact_agg.get(asset, 0) + score

    total_pos = sum(d.get('positive', 0) for d in topic_direction.values())
    total_neg = sum(d.get('negative', 0) for d in topic_direction.values())
    if total_pos > total_neg * 1.3:
        sentiment = 'positive'
    elif total_neg > total_pos * 1.3:
        sentiment = 'negative'
    else:
        sentiment = 'mixed'

    top_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        'topic_counts': dict(top_topics),
        'topic_direction': topic_direction,
        'asset_impact': asset_impact_agg,
        'sentiment': sentiment,
        'positive_count': total_pos,
        'negative_count': total_neg,
    }


def _step_mtd_delta(year: int, month: int, date_str: str) -> dict:
    """
    Step 4: MTD 델타 — 월초 Full Build 기저 대비 변화.
    LLM 불필요 (토픽 카운트 + 방향성 집계).

    (v15 refactor) 집계 로직은 `_compute_delta_from_articles`로 이동.
    기능 불변 — 월초~date_str의 분류된 기사 집합을 그대로 넘긴다.
    """
    month_str = f'{year}-{month:02d}'
    news_file = NEWS_DIR / f'{month_str}.json'
    if not news_file.exists():
        return {'status': 'skip', 'topic_counts': {}, 'sentiment': 'N/A'}

    data = json.loads(news_file.read_text(encoding='utf-8'))
    articles = data.get('articles', [])

    mtd_articles = [
        a for a in articles
        if a.get('date', '') <= date_str and '_classified_topics' in a
    ]

    delta = _compute_delta_from_articles(mtd_articles)
    return {
        'status': 'ok',
        'mtd_articles': len(mtd_articles),
        **delta,
    }


MIN_REGIME_DURATION_DAYS = 14   # cooldown: 전환 후 2주 동안 재전환 잠금
TAG_MATCH_MODE = 'exact_taxonomy'


def _judge_regime_state(regime: dict,
                         delta: dict,
                         asof_date: date,
                         taxonomy_set: set) -> tuple[dict, dict]:
    """Pure judgement — regime + delta + asof_date → (updated_regime, quality_record).

    (v15 Option C factor-out)  Rules and thresholds are **unchanged**; only
    ``date.today()`` calls became ``asof_date`` parameters. No file I/O, no
    canonical writer, no stdout print — callers are responsible for those
    side effects. Feeds both the live ``_step_regime_check`` wrapper and the
    ``tools.regime_replay`` as-of-date backfill.

    Rules (v12 판정식, 불변):
      - exact taxonomy intersection → coverage_current / coverage_today
      - sentiment_flip까지 3개 규칙 중 2개 이상 만족 → shift candidate
      - sparse tags fallback: 0개 → hold / 1개 → sentiment_flip 필수
      - 3일 연속 + cooldown(MIN_REGIME_DURATION_DAYS) 통과 → 확정
    """
    current = regime.get('current', {})
    current_tags_list = current.get('topic_tags', []) or []
    current_tags = {t for t in current_tags_list if t in taxonomy_set}
    non_taxonomy = [t for t in current_tags_list if t not in taxonomy_set]
    top_topics = list(delta.get('topic_counts', {}).keys())
    top_set = {t for t in top_topics if t in taxonomy_set}
    unknown_today = [t for t in top_topics if t not in taxonomy_set]

    intersection = current_tags & top_set
    core_today = set(top_topics[:3]) & taxonomy_set
    intersection_core = current_tags & core_today

    coverage_current = len(intersection) / max(len(current_tags), 1)
    coverage_today = len(intersection_core) / max(len(core_today), 1)

    current_direction = current.get('direction', 'neutral')
    today_sentiment = delta.get('sentiment', 'neutral')
    sentiment_flip = (
        (current_direction == 'bullish' and today_sentiment == 'negative') or
        (current_direction == 'bearish' and today_sentiment == 'positive')
    )

    low_current = coverage_current < 0.5
    low_today = coverage_today < 0.3

    rules_triggered: list[str] = []
    if low_current:
        rules_triggered.append('low_coverage_current')
    if low_today:
        rules_triggered.append('low_coverage_today')
    if sentiment_flip:
        rules_triggered.append('sentiment_flip')
    candidate_score = len(rules_triggered)

    shift_detected = False
    shift_reason = ''
    if not current_tags:
        shift_detected = False
        shift_reason = 'current.topic_tags 비어있음 — hold (description 기반 판정 금지)'
    elif len(current_tags) == 1:
        shift_detected = candidate_score >= 2 and sentiment_flip
        if not shift_detected and rules_triggered:
            shift_reason = f'sparse(1 tag) — sentiment_flip 없이 shift 보류 (rules={rules_triggered})'
        elif shift_detected:
            shift_reason = f'sparse(1 tag) + sentiment_flip 포함 {candidate_score}/3 규칙'
    else:
        shift_detected = candidate_score >= 2
        if shift_detected:
            shift_reason = (f'coverage_current={coverage_current:.2f}, '
                            f'coverage_today={coverage_today:.2f}, '
                            f'rules={rules_triggered}')
        elif rules_triggered:
            shift_reason = f'단일 규칙만 만족 ({rules_triggered}) — shift 보류'

    # ── cooldown ──
    try:
        since = date.fromisoformat(
            current.get('since', asof_date.isoformat()))
        days_in_regime = (asof_date - since).days
    except Exception:
        days_in_regime = 0
    cooldown_active = days_in_regime < MIN_REGIME_DURATION_DAYS

    # shift 연속일 카운트
    consecutive = regime.get('_shift_consecutive_days', 0)
    consecutive = consecutive + 1 if shift_detected else 0
    regime['_shift_consecutive_days'] = consecutive

    regime['shift_detected'] = False
    if consecutive >= 3 and not cooldown_active:
        new_tags = [t for t in top_topics if t in taxonomy_set][:3]
        new_narrative = ' + '.join(new_tags)
        prev_narrative = current.get('dominant_narrative', '')
        prev_description = current.get('narrative_description', '')
        regime.setdefault('history', []).append({
            'narrative': prev_narrative,
            'narrative_description': prev_description,
            'topic_tags': sorted(current_tags),
            'period': f'{current.get("since", "")} ~ {asof_date.isoformat()}',
        })
        regime['history'] = regime['history'][-24:]
        regime['previous'] = {
            'dominant_narrative': prev_narrative,
            'narrative_description': prev_description,
            'ended': asof_date.isoformat(),
        }
        direction_map = {'positive': 'bullish', 'negative': 'bearish',
                         'mixed': 'neutral'}
        regime['current'] = {
            'dominant_narrative': new_narrative,
            'topic_tags': new_tags,
            'narrative_description': '',
            'since': asof_date.isoformat(),
            'direction': direction_map.get(delta.get('sentiment', ''), 'neutral'),
            'weeks': 0,
            '_unresolved_tags': [],
        }
        regime['shift_detected'] = True
        regime['shift_description'] = f'{prev_narrative} → {new_narrative}'
        regime['_shift_consecutive_days'] = 0
        shift_reason = f'3일 연속 토픽 변화 → regime 전환: {new_narrative}'

    # weeks 자동 계산
    try:
        since = date.fromisoformat(regime['current']['since'])
        regime['current']['weeks'] = max(0, (asof_date - since).days // 7)
    except Exception:
        pass

    regime['last_daily_update'] = asof_date.isoformat()

    unknown_combined = list(dict.fromkeys(list(non_taxonomy) + list(unknown_today)))
    quality_record = {
        'date': asof_date.isoformat(),
        'tag_match_mode': TAG_MATCH_MODE,
        'decision_mode': 'multi_rule_v12',
        'current_topic_tags': sorted(current_tags),
        'top_topics_today': top_topics[:5],
        'core_today': sorted(core_today),
        'intersection_tags': sorted(intersection),
        'intersection_tags_core': sorted(intersection_core),
        'coverage_current': round(coverage_current, 3),
        'coverage_today': round(coverage_today, 3),
        'sentiment_today': today_sentiment,
        'current_direction': current_direction,
        'sentiment_flip': sentiment_flip,
        'candidate_rules_triggered': rules_triggered,
        'candidate_score': candidate_score,
        'shift_candidate': shift_detected,
        'consecutive_days': consecutive,
        'cooldown_active': cooldown_active,
        'shift_confirmed': regime.get('shift_detected', False),
        'shift_reason': shift_reason,
        'unknown_or_non_taxonomy_tags': unknown_combined,
    }
    return regime, quality_record


def _step_regime_check(delta: dict) -> dict:
    """
    Step 5: regime_memory 갱신 + regime shift 자동 감지 (canonical writer).

    **이 함수만이 regime_memory.json과 05_Regime_Canonical/ 페이지의 writer.**
    (v15) 판정 로직은 `_judge_regime_state`로 이동. 이 wrapper는 파일 I/O와
    canonical writer 호출, quality log append, 운영용 stdout print만 담당한다.
    """
    if not REGIME_FILE.exists():
        return {'status': 'skip', 'reason': 'no regime_memory'}

    from market_research.wiki.canonical import (
        normalize_regime_memory, update_canonical_regime,
    )
    from market_research.wiki.taxonomy import TAXONOMY_SET

    regime = json.loads(REGIME_FILE.read_text(encoding='utf-8'))
    regime = normalize_regime_memory(regime)

    regime, quality_record = _judge_regime_state(
        regime, delta, asof_date=date.today(), taxonomy_set=TAXONOMY_SET,
    )

    shift_detected_today = quality_record['shift_candidate']
    shift_confirmed = quality_record['shift_confirmed']
    cooldown_active = quality_record['cooldown_active']
    shift_reason = quality_record['shift_reason']
    consecutive = quality_record['consecutive_days']

    if shift_confirmed:
        print(f'  ⚠ Regime shift 확정: {shift_reason}')
    elif shift_detected_today and cooldown_active:
        # 현재 regime이 시작된 뒤 days (quality_record에는 미포함)
        try:
            since = date.fromisoformat(regime['current'].get('since', ''))
            days_in_regime = (date.today() - since).days
        except Exception:
            days_in_regime = 0
        print(f'  shift 후보이나 cooldown '
              f'({days_in_regime}/{MIN_REGIME_DURATION_DAYS}일) — 전환 보류')

    REGIME_FILE.write_text(
        json.dumps(regime, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        update_canonical_regime(REGIME_FILE)
    except Exception as exc:
        print(f'  [wiki] canonical page 갱신 실패: {exc}')

    quality_log = DATA_DIR / 'report_output' / '_regime_quality.jsonl'
    quality_log.parent.mkdir(parents=True, exist_ok=True)
    with open(quality_log, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(quality_record, ensure_ascii=False) + '\n')

    return {
        'status': 'ok',
        'current_narrative': regime['current'].get('dominant_narrative', ''),
        'topic_tags': regime['current'].get('topic_tags', []),
        'weeks': regime['current'].get('weeks', 0),
        'shift_consecutive_days': consecutive,
        'cooldown_active': cooldown_active,
        'shift_reason': shift_reason if shift_detected_today else '',
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
