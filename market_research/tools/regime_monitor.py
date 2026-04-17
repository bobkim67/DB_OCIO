# -*- coding: utf-8 -*-
"""Regime decision monitoring — passive instrumentation, no threshold changes.

Reads ``data/report_output/_regime_quality.jsonl`` and summarises the last
N days (default 14) of regime decision rows. The goal is to accumulate two
weeks of real-world signal BEFORE touching any threshold in the v12 rule
(coverage_current 0.5 / coverage_today=core_top3 / sentiment_flip).

This tool does NOT mutate any decision logic. It only aggregates what
``daily_update._step_regime_check`` has already written.

Outputs
-------
  data/report_output/regime_monitor_summary.json
  data/report_output/regime_monitor_summary.md

Usage
-----
  python -m market_research.tools.regime_monitor --days 14
  python -m market_research.tools.regime_monitor --days 7 --from 2026-04-01
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean


BASE_DIR = Path(__file__).resolve().parent.parent
QUALITY_FILE = BASE_DIR / 'data' / 'report_output' / '_regime_quality.jsonl'
OUT_JSON = BASE_DIR / 'data' / 'report_output' / 'regime_monitor_summary.json'
OUT_MD = BASE_DIR / 'data' / 'report_output' / 'regime_monitor_summary.md'


def _parse_date(s: str) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _load_quality(path: Path) -> tuple[list[dict], int]:
    """Returns (valid_rows, malformed_count). Malformed rows are skipped with warn."""
    rows: list[dict] = []
    malformed = 0
    if not path.exists():
        return rows, 0
    with open(path, encoding='utf-8') as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                print(f'[warn] malformed jsonl row at line {line_no} — skipped')
                continue
            if not isinstance(obj, dict):
                malformed += 1
                continue
            rows.append(obj)
    return rows, malformed


def _filter_window(rows: list[dict],
                   days: int,
                   from_date: date | None) -> tuple[list[dict], date, date]:
    """Select rows whose `date` falls within [start, end]. Uses the latest
    row date as anchor when from_date is None."""
    dated = [(r, _parse_date(r.get('date'))) for r in rows]
    dated = [(r, d) for r, d in dated if d is not None]
    if not dated:
        today = date.today()
        return [], today, today
    max_date = max(d for _, d in dated)
    end_date = max_date
    if from_date is not None:
        start_date = from_date
    else:
        start_date = end_date - timedelta(days=max(0, days - 1))
    window = [r for r, d in dated if start_date <= d <= end_date]
    return window, start_date, end_date


def _summarize(window: list[dict]) -> dict:
    unique_dates = {
        _parse_date(r.get('date')).isoformat()
        for r in window if _parse_date(r.get('date')) is not None
    }
    shift_candidate_days = sum(1 for r in window if r.get('shift_candidate'))
    shift_confirmed_count = sum(1 for r in window if r.get('shift_confirmed'))
    sentiment_flip_count = sum(1 for r in window if r.get('sentiment_flip'))
    cooldown_count = sum(1 for r in window if r.get('cooldown_active'))
    # sparse_fallback: detect from shift_reason containing "sparse("
    sparse_count = sum(
        1 for r in window
        if 'sparse(' in str(r.get('shift_reason') or '')
    )

    cov_cur_vals = [float(r['coverage_current']) for r in window
                    if isinstance(r.get('coverage_current'), (int, float))]
    cov_today_vals = [float(r['coverage_today']) for r in window
                      if isinstance(r.get('coverage_today'), (int, float))]

    cd_distribution = Counter()
    for r in window:
        cd = r.get('consecutive_days')
        if isinstance(cd, int):
            cd_distribution[cd] += 1

    rule_distribution = Counter()
    for r in window:
        for rule in (r.get('candidate_rules_triggered') or []):
            rule_distribution[str(rule)] += 1

    empty_tag_days = sum(
        1 for r in window
        if not (r.get('current_topic_tags') or r.get('current_tags'))
    )

    churn_proxy = (
        (shift_confirmed_count / shift_candidate_days)
        if shift_candidate_days > 0 else None
    )

    # Row-level naming: this summary aggregates jsonl ROWS, not unique days.
    # Same-date append produces multiple rows, so row counts ≠ day counts.
    # unique_dates_in_window is the companion signal for day-level coverage.
    return {
        'unique_dates_in_window': len(unique_dates),
        'shift_candidate_rows': shift_candidate_days,
        'shift_confirmed_count': shift_confirmed_count,
        'sentiment_flip_rows': sentiment_flip_count,
        'cooldown_block_rows': cooldown_count,
        'sparse_fallback_rows': sparse_count,
        'empty_tag_rows': empty_tag_days,
        'avg_coverage_current': round(mean(cov_cur_vals), 4) if cov_cur_vals else None,
        'avg_coverage_today_core3': round(mean(cov_today_vals), 4) if cov_today_vals else None,
        'consecutive_row_streak_distribution': dict(sorted(cd_distribution.items())),
        'candidate_rule_distribution': dict(rule_distribution.most_common()),
        'churn_proxy_confirmed_over_candidate_row': (
            round(churn_proxy, 4) if churn_proxy is not None else None
        ),
    }


def _render_markdown(window_meta: dict, summary: dict, rows: list[dict]) -> str:
    lines = [
        '# Regime monitor summary',
        '',
        f'- Generated: `{window_meta["generated_at"]}`',
        f'- Source: `{window_meta["source"]}`',
        f'- Window: `{window_meta["window_start"]}` ~ `{window_meta["window_end"]}` '
        f'({window_meta["window_days"]} days)',
        f'- Source rows: {window_meta["source_rows"]}  '
        f'(window rows: {window_meta["window_rows"]}, '
        f'malformed skipped: {window_meta["malformed_skipped"]})',
        '',
        '> `source_rows` = 전체 집계 대상 row 수. `window_rows` = 윈도우 내 row.',
        '> `unique_dates_in_window` = 실제 관측 일수. 동일 날짜에 여러 row가',
        '> append될 수 있으므로 row 수와 관측 일수는 다를 수 있다.',
        '> 지표 이름에 `_rows`가 붙은 것은 모두 **row-level count**이며,',
        '> day-level 해석은 `unique_dates_in_window`가 충분히 커진 뒤에만',
        '> 의미를 가진다.',
        '',
        '## Aggregate indicators (row-level operational observation)',
        '',
        '| indicator | value |',
        '|---|---|',
        f'| source_rows | {window_meta["source_rows"]} |',
        f'| window_rows | {window_meta["window_rows"]} |',
        f'| unique_dates_in_window | {summary["unique_dates_in_window"]} |',
        f'| malformed_skipped | {window_meta["malformed_skipped"]} |',
        f'| shift_candidate_rows | {summary["shift_candidate_rows"]} |',
        f'| shift_confirmed_count | {summary["shift_confirmed_count"]} |',
        f'| sentiment_flip_rows | {summary["sentiment_flip_rows"]} |',
        f'| cooldown_block_rows | {summary["cooldown_block_rows"]} |',
        f'| sparse_fallback_rows | {summary["sparse_fallback_rows"]} |',
        f'| empty_tag_rows | {summary["empty_tag_rows"]} |',
        f'| avg coverage_current | {summary["avg_coverage_current"]} |',
        f'| avg coverage_today (core top3) | {summary["avg_coverage_today_core3"]} |',
        f'| churn proxy (confirmed / candidate_row) | '
        f'{summary["churn_proxy_confirmed_over_candidate_row"]} |',
        '',
        '## consecutive_row_streak distribution',
        '',
        '| consecutive_row_streak | rows |',
        '|---|---|',
    ]
    for k, v in summary['consecutive_row_streak_distribution'].items():
        lines.append(f'| {k} | {v} |')
    lines += [
        '',
        '## candidate_rule distribution',
        '',
        '| rule | count |',
        '|---|---|',
    ]
    for rule, cnt in summary['candidate_rule_distribution'].items():
        lines.append(f'| `{rule}` | {cnt} |')

    lines += [
        '',
        '## Notes',
        '',
        '- This report is passive. v12 thresholds (coverage_current 0.5 /',
        '  coverage_today=core_top3 / sentiment_flip; 3-day consecutive + 14-day',
        '  cooldown) are **not** tuned here. Accumulate sufficient',
        '  `unique_dates_in_window` (≥14) before any re-tuning decision',
        '  (see review_packet_v12_1.md → section 6).',
        '- All `_rows` indicators count jsonl rows, not distinct days.',
        '  Same-date append (tests, debug, multi-scenario rerun) inflates row',
        '  counts without adding day-level coverage. True day-level drift',
        '  interpretation is blocked until `unique_dates_in_window` grows.',
        '- `churn_proxy` low means most candidate rows did not convert to',
        '  confirmed, which is *consistent* with the 3-day consecutive guard —',
        '  but it is not proof the guard is firing, because "consecutive" here',
        '  is row-level streak, not day-level streak. Read as operational',
        '  observation only.',
        '- `empty_tag_rows` counts rows where `current.topic_tags` was empty —',
        '  those are held intentionally (description-based judgement is banned).',
        '',
    ]
    return '\n'.join(lines)


def run(days: int = 14,
        from_date_str: str | None = None) -> dict:
    rows, malformed = _load_quality(QUALITY_FILE)
    from_date = _parse_date(from_date_str) if from_date_str else None
    window, start_d, end_d = _filter_window(rows, days, from_date)
    summary = _summarize(window)

    generated_at = datetime.now().isoformat(timespec='seconds')
    try:
        source_str = str(QUALITY_FILE.relative_to(BASE_DIR))
    except ValueError:
        source_str = str(QUALITY_FILE)
    window_meta = {
        'generated_at': generated_at,
        'source': source_str,
        'window_start': start_d.isoformat(),
        'window_end': end_d.isoformat(),
        'window_days': days,
        'source_rows': len(rows),
        'window_rows': len(window),
        'malformed_skipped': malformed,
    }
    payload = {**window_meta, 'summary': summary}

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding='utf-8')
    OUT_MD.write_text(_render_markdown(window_meta, summary, window),
                      encoding='utf-8')
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m market_research.tools.regime_monitor',
        description='Summarise _regime_quality.jsonl over the last N days.',
    )
    parser.add_argument('--days', type=int, default=14,
                        help='Window length in days (default 14)')
    parser.add_argument('--from', dest='from_date', default=None,
                        help='Explicit window start YYYY-MM-DD (overrides --days anchor)')
    args = parser.parse_args(argv)

    payload = run(days=args.days, from_date_str=args.from_date)
    s = payload['summary']
    print('=== regime_monitor summary ===')
    print(f'window: {payload["window_start"]} ~ {payload["window_end"]} '
          f'({payload["window_days"]} days)')
    print(f'source_rows: {payload["source_rows"]}  '
          f'window_rows: {payload["window_rows"]}  '
          f'unique_dates_in_window: {s["unique_dates_in_window"]}  '
          f'malformed_skipped: {payload["malformed_skipped"]}')
    print(f'shift_candidate_rows: {s["shift_candidate_rows"]}')
    print(f'shift_confirmed_count: {s["shift_confirmed_count"]}')
    print(f'sentiment_flip_rows: {s["sentiment_flip_rows"]}')
    print(f'cooldown_block_rows: {s["cooldown_block_rows"]}')
    print(f'sparse_fallback_rows: {s["sparse_fallback_rows"]}')
    print(f'empty_tag_rows: {s["empty_tag_rows"]}')
    print(f'avg coverage_current: {s["avg_coverage_current"]}')
    print(f'avg coverage_today (core_top3): {s["avg_coverage_today_core3"]}')
    print(f'churn proxy (confirmed / candidate_row): '
          f'{s["churn_proxy_confirmed_over_candidate_row"]}')
    print(f'\nwrote {OUT_JSON.name} + {OUT_MD.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
