# -*- coding: utf-8 -*-
"""Tests for regime_monitor — passive summarisation of _regime_quality.jsonl.

Cases:
  1. Empty window (no quality file) → summary has zeros, no crash.
  2. Malformed rows are skipped with warning (counted).
  3. Window filter respects --days cutoff.
  4. Idempotency: running summary twice on the same input yields same payload.
  5. Live file: run over the current repo's _regime_quality.jsonl without
     throwing; shift_confirmed_count matches direct scan.
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent


def _pass(name: str):
    print(f'  PASS — {name}')


def _fail(name: str, msg: str):
    print(f'  FAIL — {name}: {msg}')
    raise AssertionError(f'{name}: {msg}')


def _with_fake_quality_file(text: str):
    """Context manager-ish: monkey-patch QUALITY_FILE to a temp file."""
    import market_research.tools.regime_monitor as mod
    original_q = mod.QUALITY_FILE
    original_j = mod.OUT_JSON
    original_m = mod.OUT_MD

    tmp_dir = Path(tempfile.mkdtemp(prefix='regime_monitor_test_'))
    fake_q = tmp_dir / '_regime_quality.jsonl'
    fake_q.write_text(text, encoding='utf-8')
    mod.QUALITY_FILE = fake_q
    mod.OUT_JSON = tmp_dir / 'regime_monitor_summary.json'
    mod.OUT_MD = tmp_dir / 'regime_monitor_summary.md'
    return mod, original_q, original_j, original_m, tmp_dir


def _restore(mod, q, j, m):
    mod.QUALITY_FILE = q
    mod.OUT_JSON = j
    mod.OUT_MD = m


def test_case_1_empty_window_no_crash():
    import market_research.tools.regime_monitor as mod
    original_q = mod.QUALITY_FILE
    original_j = mod.OUT_JSON
    original_m = mod.OUT_MD
    tmp_dir = Path(tempfile.mkdtemp(prefix='regime_monitor_test_'))
    mod.QUALITY_FILE = tmp_dir / 'does_not_exist.jsonl'
    mod.OUT_JSON = tmp_dir / 'regime_monitor_summary.json'
    mod.OUT_MD = tmp_dir / 'regime_monitor_summary.md'
    try:
        payload = mod.run(days=14)
        if payload['total_rows_in_source'] != 0:
            _fail('case1.empty_total', f'{payload["total_rows_in_source"]}')
        s = payload['summary']
        for key in ('shift_candidate_days', 'shift_confirmed_count',
                    'sentiment_flip_count', 'cooldown_block_count'):
            if s[key] != 0:
                _fail(f'case1.{key}_zero', f'{s[key]}')
        _pass('case1: empty window → zero summary, no crash')
    finally:
        _restore(mod, original_q, original_j, original_m)


def test_case_2_malformed_skipped():
    text = (
        '{"date":"2026-04-10","shift_candidate":true,"shift_confirmed":false,'
        '"coverage_current":0.5,"coverage_today":0.0,"sentiment_flip":false,'
        '"cooldown_active":false,"consecutive_days":1,"candidate_rules_triggered":[]}\n'
        '<not valid json>\n'
        '{"date":"2026-04-11","shift_candidate":false,"shift_confirmed":false,'
        '"coverage_current":0.3,"coverage_today":0.1,"sentiment_flip":false,'
        '"cooldown_active":true,"consecutive_days":0,"candidate_rules_triggered":[]}\n'
    )
    mod, oq, oj, om, tmp = _with_fake_quality_file(text)
    try:
        payload = mod.run(days=14)
        if payload['malformed_rows'] != 1:
            _fail('case2.malformed_count', f'{payload["malformed_rows"]}')
        if payload['total_rows_in_source'] != 2:
            _fail('case2.valid_rows_kept', f'{payload["total_rows_in_source"]}')
        _pass('case2: malformed row skipped + counted')
    finally:
        _restore(mod, oq, oj, om)


def test_case_3_window_filter():
    text = '\n'.join([
        json.dumps({'date': '2026-03-01', 'shift_candidate': True,
                    'shift_confirmed': False, 'coverage_current': 0.0,
                    'coverage_today': 0.0, 'sentiment_flip': False,
                    'cooldown_active': False, 'consecutive_days': 0,
                    'candidate_rules_triggered': []}),
        json.dumps({'date': '2026-04-15', 'shift_candidate': True,
                    'shift_confirmed': True, 'coverage_current': 0.0,
                    'coverage_today': 0.0, 'sentiment_flip': True,
                    'cooldown_active': False, 'consecutive_days': 3,
                    'candidate_rules_triggered': ['sentiment_flip']}),
        json.dumps({'date': '2026-04-16', 'shift_candidate': False,
                    'shift_confirmed': False, 'coverage_current': 0.5,
                    'coverage_today': 0.2, 'sentiment_flip': False,
                    'cooldown_active': True, 'consecutive_days': 0,
                    'candidate_rules_triggered': []}),
    ]) + '\n'
    mod, oq, oj, om, tmp = _with_fake_quality_file(text)
    try:
        # days=7 anchored at max_date (2026-04-16) → start = 2026-04-10
        payload = mod.run(days=7)
        if payload['rows_in_window'] != 2:
            _fail('case3.window_excludes_old',
                  f'rows_in_window={payload["rows_in_window"]}')
        if payload['summary']['shift_confirmed_count'] != 1:
            _fail('case3.confirmed_in_window',
                  f'{payload["summary"]["shift_confirmed_count"]}')

        # days=90 → includes March row too
        payload2 = mod.run(days=90)
        if payload2['rows_in_window'] != 3:
            _fail('case3.wide_window',
                  f'rows_in_window={payload2["rows_in_window"]}')
        _pass('case3: window filter --days respected')
    finally:
        _restore(mod, oq, oj, om)


def test_case_4_idempotent():
    text = '\n'.join([
        json.dumps({'date': '2026-04-15', 'shift_candidate': True,
                    'shift_confirmed': True, 'coverage_current': 0.0,
                    'coverage_today': 0.0, 'sentiment_flip': True,
                    'cooldown_active': False, 'consecutive_days': 3,
                    'candidate_rules_triggered':
                    ['low_coverage_current', 'sentiment_flip']}),
        json.dumps({'date': '2026-04-16', 'shift_candidate': False,
                    'shift_confirmed': False, 'coverage_current': 0.5,
                    'coverage_today': 0.2, 'sentiment_flip': False,
                    'cooldown_active': True, 'consecutive_days': 0,
                    'candidate_rules_triggered': []}),
    ]) + '\n'
    mod, oq, oj, om, tmp = _with_fake_quality_file(text)
    try:
        p1 = mod.run(days=14)
        p2 = mod.run(days=14)
        # drop `generated_at` (timestamp differs) before comparison
        for p in (p1, p2):
            p.pop('generated_at', None)
        if p1 != p2:
            _fail('case4.idempotent',
                  'second run differs from first run (beyond generated_at)')
        _pass('case4: summary is idempotent on identical input')
    finally:
        _restore(mod, oq, oj, om)


def test_case_5_live_file_scan():
    live = BASE / 'data' / 'report_output' / '_regime_quality.jsonl'
    if not live.exists():
        _pass('case5: skipped (no live quality file)')
        return
    import market_research.tools.regime_monitor as mod
    payload = mod.run(days=14)

    # Count shift_confirmed directly from file, intersect with window.
    window_start = payload['window_start']
    window_end = payload['window_end']
    confirmed = 0
    with open(live, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            d = (obj.get('date') or '')[:10]
            if window_start <= d <= window_end and obj.get('shift_confirmed'):
                confirmed += 1
    if payload['summary']['shift_confirmed_count'] != confirmed:
        _fail('case5.live_matches_direct_scan',
              f'summary={payload["summary"]["shift_confirmed_count"]} '
              f'vs direct={confirmed}')
    _pass(f'case5: live file scan consistent '
          f'(confirmed={confirmed}, rows_in_window={payload["rows_in_window"]})')


def main():
    print('\n=== regime_monitor tests ===')
    cases = [
        test_case_1_empty_window_no_crash,
        test_case_2_malformed_skipped,
        test_case_3_window_filter,
        test_case_4_idempotent,
        test_case_5_live_file_scan,
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
