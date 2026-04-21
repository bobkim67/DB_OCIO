# -*- coding: utf-8 -*-
"""Tests for as-of-date regime replay (v15).

Cases:
  1. no-lookahead       — future articles do not affect past replay rows
  2. one-row-per-date   — exactly len(date range) rows in jsonl
  3. stateful rule      — 3-consecutive → confirmed, cooldown suppresses re-confirm
  4. lookback window    — articles outside [D-44, D] do not influence D
  5. live file isolation — REGIME_FILE, live quality log, canonical pages,
                           raw news JSONs all unchanged after replay
  6. summary consistency — candidate/confirmed counts in summary match jsonl
  7. null/empty day     — dates with zero articles still emit exactly one row
  8. live wrapper equivalence — v12/taxonomy tests still PASS post-refactor
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import traceback
from datetime import date, timedelta
from pathlib import Path

import market_research.tools.regime_replay as replay_mod


BASE = Path(__file__).resolve().parent.parent
LIVE_QUALITY = BASE / 'data' / 'report_output' / '_regime_quality.jsonl'
LIVE_REGIME = BASE / 'data' / 'regime_memory.json'
LIVE_CANONICAL_DIR = BASE / 'data' / 'wiki' / '05_Regime_Canonical'
LIVE_NEWS_DIR = BASE / 'data' / 'news'


def _pass(name: str):
    print(f'  PASS — {name}')


def _fail(name: str, msg: str):
    print(f'  FAIL — {name}: {msg}')
    raise AssertionError(f'{name}: {msg}')


def _md5(path: Path) -> str:
    if not path.exists():
        return ''
    return hashlib.md5(path.read_bytes()).hexdigest()


def _make_tmp_news_dir(articles_by_month: dict[str, list[dict]]) -> Path:
    """Create a temp directory with fake news JSON files."""
    tmp = Path(tempfile.mkdtemp(prefix='regime_replay_test_'))
    for month, arts in articles_by_month.items():
        (tmp / f'{month}.json').write_text(
            json.dumps({'month': month, 'total': len(arts), 'articles': arts},
                       ensure_ascii=False),
            encoding='utf-8',
        )
    return tmp


def _article(d: str, topic: str, direction: str = 'negative',
             title_suffix: str = '') -> dict:
    """Build a minimal classified article."""
    return {
        'date': d,
        'source': '테스트매체',
        'title': f'test article {d} {topic} {title_suffix}',
        'description': f'description for {topic} on {d}',
        'url': f'https://example.com/{d}/{topic}/{title_suffix}',
        '_classified_topics': [{'topic': topic, 'direction': direction,
                                'intensity': 5}],
        '_asset_impact_vector': {},
    }


def _run_replay(start: date, end: date, tmp_news: Path,
                lookback_days: int = 45) -> tuple[dict, Path, Path, Path]:
    tmp_out = Path(tempfile.mkdtemp(prefix='regime_replay_out_'))
    out_jsonl = tmp_out / '_regime_quality_replay.jsonl'
    out_json = tmp_out / 'regime_replay_summary.json'
    out_md = tmp_out / 'regime_replay_summary.md'
    payload = replay_mod.replay(
        start=start, end=end, lookback_days=lookback_days,
        out_jsonl=out_jsonl, out_json=out_json, out_md=out_md,
        news_dir=tmp_news,
    )
    return payload, out_jsonl, out_json, out_md


# ─────────────────────────────────────────────────────────────

def test_case_1_no_lookahead():
    """Future articles must not influence past asof rows."""
    base_articles = [_article('2026-04-10', '지정학', 'negative', f'a{i}')
                     for i in range(3)]
    # baseline: no future article
    tmp1 = _make_tmp_news_dir({'2026-04': list(base_articles)})
    p1, j1, _, _ = _run_replay(date(2026, 4, 10), date(2026, 4, 10), tmp1)
    row1 = json.loads(j1.read_text(encoding='utf-8').strip())

    # perturbed: add many future articles (different topic)
    future_articles = [
        _article('2026-04-20', '환율_FX', 'positive', f'f{i}')
        for i in range(50)
    ]
    tmp2 = _make_tmp_news_dir({'2026-04': base_articles + future_articles})
    p2, j2, _, _ = _run_replay(date(2026, 4, 10), date(2026, 4, 10), tmp2)
    row2 = json.loads(j2.read_text(encoding='utf-8').strip())

    # Rows must be identical in content (apart from metadata we added)
    for k in ('date', 'top_topics_today', 'coverage_current',
              'coverage_today', 'shift_candidate', 'shift_confirmed',
              'consecutive_days', 'today_article_count'):
        if row1.get(k) != row2.get(k):
            _fail('case1.invariant',
                  f'field `{k}` changed: {row1.get(k)} vs {row2.get(k)}')
    _pass('case1: future articles do not affect past asof replay')


def test_case_2_one_row_per_date():
    tmp = _make_tmp_news_dir({
        '2026-04': [_article('2026-04-05', '지정학', 'negative', f'a{i}')
                    for i in range(2)],
    })
    payload, j, _, _ = _run_replay(date(2026, 4, 1), date(2026, 4, 17), tmp)
    rows = [line for line in j.read_text(encoding='utf-8').splitlines()
            if line.strip()]
    if len(rows) != 17:
        _fail('case2.row_count', f'expected 17 rows, got {len(rows)}')
    # all rows have unique dates
    dates = [json.loads(r)['date'] for r in rows]
    if len(set(dates)) != 17:
        _fail('case2.unique_dates', f'duplicates: {dates}')
    _pass('case2: exactly 17 rows for 17-day window')


def test_case_3_stateful_rule():
    """Driven synthetic fixture: 3 consecutive candidate days → confirmed.
    Then cooldown must suppress re-confirm on subsequent candidate day.

    Strategy: regime starts neutral_empty. After first confirm (day 3),
    cooldown is active for 14 days. We then verify a further candidate
    day within cooldown does NOT re-confirm.

    To force a confirm from neutral_empty, we seed a regime that already
    has topic_tags via the replay's internal regime_in state bypass —
    but that state isn't publicly exposed. So instead we test the
    underlying _judge_regime_state directly, which is what replay loops
    over internally.
    """
    from market_research.pipeline.daily_update import _judge_regime_state
    from market_research.wiki.taxonomy import TAXONOMY_SET

    # Seed regime with existing tags and since set 30 days ago (cooldown past)
    regime = {
        'current': {
            'dominant_narrative': '지정학 + 물가_인플레이션',
            'topic_tags': ['지정학', '물가_인플레이션'],
            'narrative_description': '',
            'since': (date(2026, 4, 1) - timedelta(days=30)).isoformat(),
            'direction': 'bearish',
            'weeks': 4,
        },
        'history': [],
        '_shift_consecutive_days': 0,
    }
    # delta with top topics totally different + sentiment flip (bullish-ish)
    delta = {
        'topic_counts': {
            '환율_FX': 10, '에너지_원자재': 8, '통화정책': 6,
        },
        'sentiment': 'positive',
    }

    # Day 1: candidate yes, not confirmed
    regime, q1 = _judge_regime_state(
        regime, delta, asof_date=date(2026, 4, 1), taxonomy_set=TAXONOMY_SET)
    if not q1['shift_candidate']:
        _fail('case3.d1_candidate', f'q1={q1}')
    if q1['shift_confirmed']:
        _fail('case3.d1_not_confirmed_yet', 'confirmed too early')

    # Day 2
    regime, q2 = _judge_regime_state(
        regime, delta, asof_date=date(2026, 4, 2), taxonomy_set=TAXONOMY_SET)
    if q2['consecutive_days'] != 2:
        _fail('case3.d2_consecutive', f'{q2["consecutive_days"]}')

    # Day 3 → confirm. quality_record reports consecutive=3 for the day
    # of confirmation (this matches live _regime_quality.jsonl behaviour);
    # the stored streak `regime['_shift_consecutive_days']` is reset to 0
    # for the next iteration.
    regime, q3 = _judge_regime_state(
        regime, delta, asof_date=date(2026, 4, 3), taxonomy_set=TAXONOMY_SET)
    if not q3['shift_confirmed']:
        _fail('case3.d3_confirmed', f'q3={q3}')
    if q3['consecutive_days'] != 3:
        _fail('case3.d3_consecutive_on_confirm',
              f'expected 3, got {q3["consecutive_days"]}')
    if regime.get('_shift_consecutive_days', -1) != 0:
        _fail('case3.d3_streak_state_reset',
              f'stored streak not reset: '
              f'{regime.get("_shift_consecutive_days")}')

    # Day 4 — still within 14-day cooldown (since just reset on Day 3)
    regime, q4 = _judge_regime_state(
        regime, delta, asof_date=date(2026, 4, 4), taxonomy_set=TAXONOMY_SET)
    if not q4['cooldown_active']:
        _fail('case3.d4_cooldown_active',
              f'cooldown should be active, got {q4}')

    # Day 5-6 (still cooldown): even 3 candidates in a row must not confirm
    regime, q5 = _judge_regime_state(
        regime, delta, asof_date=date(2026, 4, 5), taxonomy_set=TAXONOMY_SET)
    regime, q6 = _judge_regime_state(
        regime, delta, asof_date=date(2026, 4, 6), taxonomy_set=TAXONOMY_SET)
    regime, q7 = _judge_regime_state(
        regime, delta, asof_date=date(2026, 4, 7), taxonomy_set=TAXONOMY_SET)
    # q7 should have consecutive_days >= 3, but shift_confirmed=False due
    # to cooldown_active
    if not q7['cooldown_active']:
        _fail('case3.d7_cooldown', f'q7 cooldown={q7}')
    if q7['shift_confirmed']:
        _fail('case3.d7_not_confirmed_in_cooldown',
              f'cooldown should block confirm, got {q7}')

    _pass('case3: 3-consecutive → confirm; cooldown blocks re-confirm')


def test_case_4_lookback_window():
    """Articles outside [D - lookback + 1, D] must be ignored."""
    in_window = [_article('2026-04-16', '지정학', 'negative', f'i{i}')
                 for i in range(3)]
    # far past: lookback=10 → anything <= 2026-04-06 is outside
    far_past = [_article('2026-03-01', '환율_FX', 'positive', f'p{i}')
                for i in range(50)]
    tmp = _make_tmp_news_dir({
        '2026-03': list(far_past),
        '2026-04': list(in_window),
    })
    payload, j, _, _ = _run_replay(date(2026, 4, 16), date(2026, 4, 16), tmp,
                                    lookback_days=10)
    row = json.loads(j.read_text(encoding='utf-8').strip())
    # window should contain only the 3 in-window articles (asof-only today)
    # today_article_count is the classified slice on asof=2026-04-16
    if row['today_article_count'] != 3:
        _fail('case4.today_slice',
              f'expected 3 today articles, got {row["today_article_count"]}')
    # window_article_count should not include the 50 far-past articles
    if row['window_article_count'] > 20:  # generous upper bound
        _fail('case4.window_slice',
              f'far-past leaked in: window_article_count={row["window_article_count"]}')
    _pass('case4: lookback window excludes articles outside range')


def test_case_5_live_file_isolation():
    """Replay must not mutate any live artefact."""
    # Snapshot md5 of live files before replay
    before = {
        'regime_memory': _md5(LIVE_REGIME),
        'live_quality': _md5(LIVE_QUALITY),
    }
    canonical_files = (sorted(LIVE_CANONICAL_DIR.glob('*.md'))
                       if LIVE_CANONICAL_DIR.exists() else [])
    before_canonical = {f.name: _md5(f) for f in canonical_files}
    news_files = sorted(LIVE_NEWS_DIR.glob('*.json'))
    before_news = {f.name: _md5(f) for f in news_files}

    # Run a small replay against real news data but with isolated outputs
    tmp_out = Path(tempfile.mkdtemp(prefix='isolation_test_out_'))
    payload = replay_mod.replay(
        start=date(2026, 4, 16), end=date(2026, 4, 17),
        lookback_days=10,
        out_jsonl=tmp_out / '_regime_quality_replay.jsonl',
        out_json=tmp_out / 'regime_replay_summary.json',
        out_md=tmp_out / 'regime_replay_summary.md',
    )
    # Re-check md5
    after = {
        'regime_memory': _md5(LIVE_REGIME),
        'live_quality': _md5(LIVE_QUALITY),
    }
    after_canonical = {f.name: _md5(f)
                       for f in (sorted(LIVE_CANONICAL_DIR.glob('*.md'))
                                 if LIVE_CANONICAL_DIR.exists() else [])}
    after_news = {f.name: _md5(f) for f in sorted(LIVE_NEWS_DIR.glob('*.json'))}

    for k in before:
        if before[k] != after[k]:
            _fail('case5.' + k, f'{k} mutated during replay')
    if before_canonical != after_canonical:
        diffs = [n for n in before_canonical
                 if before_canonical[n] != after_canonical.get(n)]
        _fail('case5.canonical', f'canonical pages mutated: {diffs}')
    if before_news != after_news:
        diffs = [n for n in before_news
                 if before_news[n] != after_news.get(n)]
        _fail('case5.news', f'raw news JSONs mutated: {diffs}')
    _pass('case5: live artefacts unchanged (REGIME_FILE, live jsonl, '
          'canonical pages, raw news JSONs)')


def test_case_6_summary_consistency():
    """Summary counters must equal direct jsonl scan."""
    articles = [_article(f'2026-04-{d:02d}', '지정학', 'negative', f'a{i}')
                for d in range(5, 15) for i in range(2)]
    tmp = _make_tmp_news_dir({'2026-04': articles})
    payload, j, jj, _ = _run_replay(date(2026, 4, 5), date(2026, 4, 14), tmp)
    # scan jsonl directly
    rows = [json.loads(ln) for ln in j.read_text(encoding='utf-8').splitlines()
            if ln.strip()]
    candidate_days = sum(1 for r in rows if r.get('shift_candidate'))
    confirmed = sum(1 for r in rows if r.get('shift_confirmed'))
    s = payload['summary']
    if s['candidate_days'] != candidate_days:
        _fail('case6.candidate', f'{s["candidate_days"]} vs {candidate_days}')
    if s['confirmed_count'] != confirmed:
        _fail('case6.confirmed', f'{s["confirmed_count"]} vs {confirmed}')
    if payload['total_replay_dates'] != len(rows):
        _fail('case6.total', f'{payload["total_replay_dates"]} vs {len(rows)}')
    _pass(f'case6: summary consistent (candidate={candidate_days}, '
          f'confirmed={confirmed}, total={len(rows)})')


def test_case_7_null_empty_day_handling():
    """Dates with zero articles must still emit a row."""
    # Only one article on 2026-04-10; other days empty
    articles = [_article('2026-04-10', '지정학', 'negative', 'solo')]
    tmp = _make_tmp_news_dir({'2026-04': articles})
    payload, j, _, _ = _run_replay(date(2026, 4, 8), date(2026, 4, 12), tmp)
    rows = [json.loads(ln) for ln in j.read_text(encoding='utf-8').splitlines()
            if ln.strip()]
    if len(rows) != 5:
        _fail('case7.row_count', f'expected 5 rows, got {len(rows)}')
    # days without articles should have today_article_count=0 but still
    # emit a quality_record
    empty_day_rows = [r for r in rows if r['today_article_count'] == 0]
    if len(empty_day_rows) != 4:
        _fail('case7.empty_days',
              f'expected 4 empty-day rows, got {len(empty_day_rows)}')
    # check no crash on empty-day judgement (fields present)
    for r in empty_day_rows:
        for k in ('shift_candidate', 'shift_confirmed', 'coverage_current',
                  'coverage_today', 'current_topic_tags', 'top_topics_today'):
            if k not in r:
                _fail('case7.field_missing', f'`{k}` in empty-day row')
    _pass('case7: zero-article days still emit exactly one row each')


def test_case_8_live_wrapper_equivalence():
    """Existing regime/taxonomy regression must still PASS after factor-out.

    Runs the other two regime suites as subprocesses; any failure there
    means the refactor has changed live behaviour.
    """
    import subprocess
    for suite in ('test_taxonomy_contract', 'test_regime_decision_v12'):
        proc = subprocess.run(
            [sys.executable, '-m', f'market_research.tests.{suite}'],
            capture_output=True, text=True, cwd=str(BASE.parent),
        )
        if proc.returncode != 0:
            _fail('case8.' + suite,
                  f'returncode={proc.returncode}\nstdout={proc.stdout[-500:]}\n'
                  f'stderr={proc.stderr[-500:]}')
    _pass('case8: live wrapper equivalence — taxonomy + regime_v12 PASS')


def main():
    print('\n=== regime_replay tests ===')
    cases = [
        test_case_1_no_lookahead,
        test_case_2_one_row_per_date,
        test_case_3_stateful_rule,
        test_case_4_lookback_window,
        test_case_5_live_file_isolation,
        test_case_6_summary_consistency,
        test_case_7_null_empty_day_handling,
        test_case_8_live_wrapper_equivalence,
    ]
    results = []
    for fn in cases:
        try:
            fn()
            results.append((fn.__name__, 'PASS'))
        except AssertionError as exc:
            results.append((fn.__name__, f'FAIL: {exc}'))
        except Exception:
            traceback.print_exc()
            results.append((fn.__name__, 'ERROR'))

    print('\n=== Summary ===')
    for name, status in results:
        print(f'  {status:8s} {name}')
    failed = [n for n, s in results if not s.startswith('PASS')]
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
