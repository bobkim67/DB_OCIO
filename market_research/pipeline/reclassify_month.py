# -*- coding: utf-8 -*-
"""Reclassify Month — Phase 2.5 회귀 검증용 경량 경로.

Step 1.3 (naver_research adapter) + Step 2 (adapted 전용 분류) + Step 2.5 (refine) 만
월별로 재실행. GraphRAG / regime / 매크로 / debate 는 건드리지 않는다.

news 파일은 건드리지 않고 audit 만 수행 — `_classified_topics` / `_event_salience`
부착률만 보고. 이상치가 크면 사용자가 별도로 `classify_month` 를 돌려야 한다.

사용:
    python -m market_research.pipeline.reclassify_month --month 2026-02 2026-03 2026-04
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).resolve().parent.parent
NEWS_DIR = BASE_DIR / 'data' / 'news'


def _audit_news(month_str: str) -> dict:
    """news/{month}.json 의 분류/salience 부착률만 읽어서 리턴.

    파일을 수정하지 않는다.
    """
    p = NEWS_DIR / f'{month_str}.json'
    if not p.exists():
        return {'status': 'missing', 'path': str(p)}
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception as exc:
        return {'status': 'error', 'error': str(exc), 'path': str(p)}
    arts = data.get('articles', [])
    total = len(arts)
    if total == 0:
        return {'status': 'empty', 'total': 0}

    no_topics = sum(
        1 for a in arts
        if '_classified_topics' not in a or not a.get('_classified_topics'))
    no_topics_field = sum(1 for a in arts if '_classified_topics' not in a)
    no_salience = sum(1 for a in arts if a.get('_event_salience') is None)
    return {
        'status': 'ok',
        'total': total,
        'no_topics_field': no_topics_field,
        'no_topics_or_empty': no_topics,
        'no_salience': no_salience,
        'topic_coverage_pct': round((total - no_topics) / total * 100, 1),
        'salience_coverage_pct': round((total - no_salience) / total * 100, 1),
    }


def _evidence_snapshot(year: int, month: int, target_count: int = 15) -> dict:
    """debate_engine 의 _build_evidence_candidates 를 불러 nr/news 비율 확인."""
    from market_research.report.debate_engine import _build_evidence_candidates
    high, ids, lines, dbg = _build_evidence_candidates(
        year, month, target_count=target_count, start_idx=1)
    nr = sum(1 for a in high if a.get('source_type') == 'naver_research')
    news = len(high) - nr
    return {
        'picked': len(high),
        'nr': nr,
        'news': news,
        'target_count': target_count,
        'research_pool_size': dbg.get('research_pool_size', 0),
        'news_pool_size': dbg.get('news_pool_size', 0),
    }


def run_month(month_str: str) -> dict:
    """단일 월 재분류/정제 + audit.

    반환 구조:
        {
          'month': 'YYYY-MM',
          'adapter': {...},
          'classify_adapted': {...},
          'refine': {...},
          'news_audit': {...},
          'evidence': {...},
        }
    """
    from market_research.pipeline.daily_update import (
        _step_naver_research_adapter, _step_refine,
    )
    from market_research.analyze.news_classifier import classify_adapted_month

    print(f'\n══════════════════════════════════════════')
    print(f'  Reclassify month: {month_str}')
    print(f'══════════════════════════════════════════')

    y, m = int(month_str[:4]), int(month_str[5:7])
    out: dict = {'month': month_str}

    t0 = time.time()
    out['adapter'] = _step_naver_research_adapter(month_str)
    print(f'[1.3] adapter: {out["adapter"]} (+{time.time()-t0:.1f}s)')

    t0 = time.time()
    out['classify_adapted'] = classify_adapted_month(month_str)
    print(f'[2]   classify: {out["classify_adapted"]} (+{time.time()-t0:.1f}s)')

    t0 = time.time()
    out['refine'] = _step_refine(month_str)
    print(f'[2.5] refine:   {out["refine"]} (+{time.time()-t0:.1f}s)')

    out['news_audit'] = _audit_news(month_str)
    print(f'[audit] news:   {out["news_audit"]}')

    try:
        out['evidence'] = _evidence_snapshot(y, m, target_count=15)
        print(f'[evidence] {out["evidence"]}')
    except Exception as exc:
        out['evidence'] = {'error': str(exc)}
        print(f'[evidence] 실패: {exc}')

    return out


def _final_report(reports: list[dict]) -> None:
    print(f'\n══════════════════════════════════════════')
    print(f'  최종 보고')
    print(f'══════════════════════════════════════════')

    print('\n[1] 월별 adapted 재분류 건수')
    for r in reports:
        ca = r.get('classify_adapted', {})
        print(f'  {r["month"]}: total={ca.get("total", 0)} '
              f'classified={ca.get("classified", 0)} '
              f'newly={ca.get("newly_classified", 0)} '
              f'unclassified={ca.get("unclassified", 0)}')

    print('\n[2] 월별 refine 완료 여부')
    for r in reports:
        rf = r.get('refine', {})
        sources = rf.get('sources', {})
        news_r = sources.get('news', {}).get('status', '—')
        nr_r = sources.get('naver_research', {}).get('status', '—')
        print(f'  {r["month"]}: status={rf.get("status", "?")} '
              f'news={news_r} naver_research={nr_r} '
              f'primary={rf.get("primary_count", 0)} '
              f'fallback={rf.get("fallback_count", 0)}')

    print('\n[3] 월별 evidence selection (target 15)')
    for r in reports:
        ev = r.get('evidence', {})
        if 'error' in ev:
            print(f'  {r["month"]}: ERROR {ev["error"]}')
            continue
        nr = ev.get('nr', 0)
        news = ev.get('news', 0)
        picked = ev.get('picked', 0)
        ok = '✅' if 8 <= nr <= 12 else ('⚠️' if ev.get('research_pool_size', 0) > 0 else '🟡 news-only fallback')
        print(f'  {r["month"]}: picked={picked} nr={nr} news={news} '
              f'research_pool={ev.get("research_pool_size", 0)} '
              f'news_pool={ev.get("news_pool_size", 0)} {ok}')

    print('\n[4] news audit (건드리지 않음)')
    for r in reports:
        au = r.get('news_audit', {})
        if au.get('status') != 'ok':
            print(f'  {r["month"]}: {au.get("status")} {au.get("error", "")}')
            continue
        print(f'  {r["month"]}: total={au["total"]} '
              f'topic_coverage={au["topic_coverage_pct"]}% '
              f'(no_topics={au["no_topics_or_empty"]}), '
              f'salience_coverage={au["salience_coverage_pct"]}% '
              f'(no_salience={au["no_salience"]})')

    print('\n[5] Acceptance 판정 (월별 15건, nr 8~12)')
    passed = []
    skipped = []
    for r in reports:
        ev = r.get('evidence', {})
        nr = ev.get('nr', 0)
        pool = ev.get('research_pool_size', 0)
        if pool == 0:
            skipped.append(r['month'])
        elif 8 <= nr <= 12:
            passed.append(r['month'])
    print(f'  PASS: {passed}')
    print(f'  SKIP (research_pool=0, fallback news-only): {skipped}')
    others = [r['month'] for r in reports
              if r['month'] not in passed and r['month'] not in skipped]
    if others:
        print(f'  FAIL/경계: {others}')


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Reclassify naver_research adapted monthly (Phase 2.5 검증용 경량 경로)')
    parser.add_argument('--month', nargs='+', required=True,
                        help="'YYYY-MM' 형식 하나 이상 (예: --month 2026-02 2026-03 2026-04)")
    args = parser.parse_args()

    reports = []
    for m in args.month:
        reports.append(run_month(m))

    _final_report(reports)
    return 0


if __name__ == '__main__':
    sys.exit(main())
