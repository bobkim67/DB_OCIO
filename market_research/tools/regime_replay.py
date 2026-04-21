# -*- coding: utf-8 -*-
"""as-of-date regime replay / backfill — supplementary, not live monitor.

Purpose
-------
Regenerate past per-day regime judgements without look-ahead bias, so that
threshold re-evaluation / false-positive / false-negative checks have a
cleaner signal than the same-date-append live log.

**This is a supplementary verification path.** It never writes to:
  - `REGIME_FILE` (data/regime_memory.json)
  - `_regime_quality.jsonl` (live)
  - `05_Regime_Canonical/*`
  - raw news JSON files

Outputs (all overwrite-on-rerun for reproducibility):
  - `data/report_output/_regime_quality_replay.jsonl`  (one row per date)
  - `data/report_output/regime_replay_summary.json`
  - `data/report_output/regime_replay_summary.md`

Algorithm
---------
For each date D in [start, end]:
  1. Load news JSON for months touched by `[D - lookback+1, D]`.
  2. Filter articles to that as-of window (``pub_date in [D-44, D]``).
     No article with `date > D` is ever touched.
  3. Deep-copy the filtered articles so original file dicts are untouched.
  4. Re-run refinement on the copy:
       process_dedupe_and_events → compute_salience_batch
       → fallback_classify_uncategorized
     with `bm_anomaly_dates` trimmed to `date <= D`.
  5. Compute today's delta from `articles where date == D` using the live
     `_compute_delta_from_articles` function (shared, drift-free).
  6. Judge regime state via `_judge_regime_state(carry_state, delta, D)`.
  7. Carry updated regime state forward to D+1.
  8. Append one row to replay jsonl.

Initial state (D = start):
  neutral-empty — `topic_tags=[]`, `direction='neutral'`,
  `since=start_date`, `_shift_consecutive_days=0`. Never read from
  `regime_memory.json` (would leak live state into historical replay).

CLI
---
    python -m market_research.tools.regime_replay \\
        --start 2026-04-01 --end 2026-04-17
    python -m market_research.tools.regime_replay \\
        --start 2026-04-01 --end 2026-04-17 --lookback-days 75
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean

BASE_DIR = Path(__file__).resolve().parent.parent
NEWS_DIR = BASE_DIR / 'data' / 'news'
OUT_JSONL = BASE_DIR / 'data' / 'report_output' / '_regime_quality_replay.jsonl'
OUT_JSON = BASE_DIR / 'data' / 'report_output' / 'regime_replay_summary.json'
OUT_MD = BASE_DIR / 'data' / 'report_output' / 'regime_replay_summary.md'

DEFAULT_LOOKBACK_DAYS = 45


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _parse_date(s: str) -> date:
    return datetime.strptime(str(s)[:10], '%Y-%m-%d').date()


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _months_touched(start: date, end: date) -> list[str]:
    """Return [YYYY-MM, ...] months covering [start, end] inclusive."""
    months: list[str] = []
    d = date(start.year, start.month, 1)
    end_anchor = date(end.year, end.month, 1)
    while d <= end_anchor:
        months.append(f'{d.year:04d}-{d.month:02d}')
        # advance to first of next month
        if d.month == 12:
            d = date(d.year + 1, 1, 1)
        else:
            d = date(d.year, d.month + 1, 1)
    return months


def _load_articles_for_months(months: list[str],
                               news_dir: Path | None = None) -> list[dict]:
    """Load union of news articles across the given months.

    Returns raw dict list — callers MUST deep-copy before mutating.
    """
    root = Path(news_dir) if news_dir is not None else NEWS_DIR
    articles: list[dict] = []
    for m in months:
        f = root / f'{m}.json'
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        for a in data.get('articles', []):
            if isinstance(a, dict):
                articles.append(a)
    return articles


def _filter_asof_window(articles: list[dict],
                         asof: date,
                         lookback_days: int) -> list[dict]:
    """articles where (asof - lookback_days + 1) <= date <= asof."""
    window_start = asof - timedelta(days=max(0, lookback_days - 1))
    out: list[dict] = []
    for a in articles:
        d_str = a.get('date') or ''
        try:
            d = _parse_date(d_str)
        except Exception:
            continue
        if window_start <= d <= asof:
            out.append(a)
    return out


def _neutral_empty_state(start: date) -> dict:
    """Replay initial state. Never reads live regime_memory.json."""
    return {
        'current': {
            'dominant_narrative': '',
            'topic_tags': [],
            'narrative_description': '',
            'since': start.isoformat(),
            'direction': 'neutral',
            'weeks': 0,
            '_unresolved_tags': [],
        },
        'history': [],
        '_shift_consecutive_days': 0,
    }


def _bm_anomaly_safe(asof: date) -> set:
    """Load BM anomaly dates for asof.month, filtered to date <= asof.

    Falls back to an empty set if DB access fails (replay should not crash
    when DB is offline). `load_bm_anomaly_dates` internally uses a 3-month
    lookback that may include data past asof; we prune it here.
    """
    try:
        from market_research.core.salience import load_bm_anomaly_dates
        raw = load_bm_anomaly_dates(asof.year, asof.month)
    except Exception:
        return set()
    if not raw:
        return set()
    safe: set = set()
    for d in raw:
        try:
            if _parse_date(str(d)) <= asof:
                safe.add(d)
        except Exception:
            continue
    return safe


# ─────────────────────────────────────────────────────────────
# Core replay
# ─────────────────────────────────────────────────────────────

def _refine_asof(articles: list[dict], bm_anomaly: set) -> list[dict]:
    """Run refinement on a deep-copied article list.

    Assumes caller has already filtered to the as-of window. Returns the
    refined list (copies, original dicts untouched).
    """
    from market_research.core.dedupe import process_dedupe_and_events
    from market_research.core.salience import (
        compute_salience_batch, fallback_classify_uncategorized,
    )
    copied = copy.deepcopy(articles)
    copied = process_dedupe_and_events(copied)
    copied = compute_salience_batch(copied, bm_anomaly)
    fallback_classify_uncategorized(copied, bm_anomaly)
    return copied


def replay(start: date,
           end: date,
           lookback_days: int = DEFAULT_LOOKBACK_DAYS,
           out_jsonl: Path | None = None,
           out_json: Path | None = None,
           out_md: Path | None = None,
           news_dir: Path | None = None) -> dict:
    """Execute the as-of-date replay loop.

    All output paths are overridable for testability; defaults write to
    the repo's ``data/report_output/`` directory.
    """
    from market_research.pipeline.daily_update import (
        _compute_delta_from_articles, _judge_regime_state,
    )
    from market_research.wiki.taxonomy import TAXONOMY_SET

    t0 = time.time()
    out_jsonl = out_jsonl or OUT_JSONL
    out_json = out_json or OUT_JSON
    out_md = out_md or OUT_MD

    # Preload months that cover [start - lookback + 1, end]
    earliest_asof = start
    earliest_window = earliest_asof - timedelta(days=max(0, lookback_days - 1))
    months = _months_touched(earliest_window, end)

    all_articles = _load_articles_for_months(months, news_dir=news_dir)
    total_loaded = len(all_articles)

    regime = _neutral_empty_state(start)
    rows: list[dict] = []
    per_date_article_counts: list[int] = []

    for asof in _daterange(start, end):
        window_articles = _filter_asof_window(
            all_articles, asof, lookback_days,
        )
        # Refine as-of window (deep copy inside)
        bm_anomaly = _bm_anomaly_safe(asof)
        refined = _refine_asof(window_articles, bm_anomaly)

        # today's classified slice (already-classified articles on asof)
        today_articles = [
            a for a in refined
            if a.get('date') == asof.isoformat()
            and '_classified_topics' in a
        ]
        per_date_article_counts.append(len(today_articles))

        delta = _compute_delta_from_articles(today_articles, asof_date=asof)

        regime, quality_record = _judge_regime_state(
            regime, delta, asof_date=asof, taxonomy_set=TAXONOMY_SET,
        )
        # attach replay metadata
        quality_record['mode'] = 'asof_replay'
        quality_record['lookback_days'] = lookback_days
        quality_record['today_article_count'] = len(today_articles)
        quality_record['window_article_count'] = len(refined)
        rows.append(quality_record)

    elapsed = round(time.time() - t0, 2)

    # ── write jsonl (overwrite) ──
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(out_jsonl, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')

    # ── summary ──
    total_dates = len(rows)
    unique_dates = len({r['date'] for r in rows})
    candidate_days = sum(1 for r in rows if r.get('shift_candidate'))
    confirmed_count = sum(1 for r in rows if r.get('shift_confirmed'))
    sentiment_flip_days = sum(1 for r in rows if r.get('sentiment_flip'))
    cooldown_days = sum(1 for r in rows if r.get('cooldown_active'))
    empty_tag_days = sum(
        1 for r in rows if not r.get('current_topic_tags')
    )
    cov_cur = [r['coverage_current'] for r in rows
               if isinstance(r.get('coverage_current'), (int, float))]
    cov_today = [r['coverage_today'] for r in rows
                 if isinstance(r.get('coverage_today'), (int, float))]
    cd_dist = Counter(r.get('consecutive_days') for r in rows)
    churn = (confirmed_count / candidate_days) if candidate_days > 0 else None

    avg_articles = (
        round(sum(per_date_article_counts) / len(per_date_article_counts), 2)
        if per_date_article_counts else 0.0
    )

    payload = {
        'mode': 'asof_replay',
        'note': 'supplementary verification — NOT live monitor',
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'start': start.isoformat(),
        'end': end.isoformat(),
        'lookback_days': lookback_days,
        'initial_state': 'neutral_empty',
        'total_replay_dates': total_dates,
        'unique_replay_dates': unique_dates,
        'total_loaded_articles': total_loaded,
        'per_date_avg_article_count': avg_articles,
        'runtime_seconds': elapsed,
        'summary': {
            'candidate_days': candidate_days,
            'confirmed_count': confirmed_count,
            'sentiment_flip_days': sentiment_flip_days,
            'cooldown_days': cooldown_days,
            'empty_tag_days': empty_tag_days,
            'avg_coverage_current': (
                round(mean(cov_cur), 4) if cov_cur else None
            ),
            'avg_coverage_today_core3': (
                round(mean(cov_today), 4) if cov_today else None
            ),
            'consecutive_day_distribution': dict(sorted(cd_dist.items())),
            'churn_proxy_confirmed_over_candidate_day': (
                round(churn, 4) if churn is not None else None
            ),
        },
    }
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    md_lines = [
        '# Regime replay summary',
        '',
        '> **Historical replay / backfill — NOT live monitor.**',
        '> Supplementary verification path. Does not touch',
        '> `regime_memory.json`, live `_regime_quality.jsonl`, or',
        '> `05_Regime_Canonical/*`. Thresholds are not tuned from this',
        '> artefact alone.',
        '',
        f'- Generated: `{payload["generated_at"]}`',
        f'- Window: `{payload["start"]}` ~ `{payload["end"]}`',
        f'- Lookback: **{lookback_days}** days',
        f'- Initial state: `{payload["initial_state"]}`',
        f'- Total replay dates: **{total_dates}**  (unique: {unique_dates})',
        f'- Total loaded articles (union across touched months): '
        f'{total_loaded:,}',
        f'- Per-date avg article count (asof-slice): {avg_articles}',
        f'- Runtime: **{elapsed} s**',
        '',
        '## Aggregate indicators (replay)',
        '',
        '| indicator | value |',
        '|---|---|',
        f'| candidate_days | {candidate_days} |',
        f'| confirmed_count | {confirmed_count} |',
        f'| sentiment_flip_days | {sentiment_flip_days} |',
        f'| cooldown_days | {cooldown_days} |',
        f'| empty_tag_days | {empty_tag_days} |',
        f'| avg coverage_current | {payload["summary"]["avg_coverage_current"]} |',
        f'| avg coverage_today (core_top3) | '
        f'{payload["summary"]["avg_coverage_today_core3"]} |',
        f'| churn proxy (confirmed / candidate_day) | '
        f'{payload["summary"]["churn_proxy_confirmed_over_candidate_day"]} |',
        '',
        '## consecutive_day_distribution',
        '',
        '| consecutive_days | count |',
        '|---|---|',
    ]
    for k, v in payload['summary']['consecutive_day_distribution'].items():
        md_lines.append(f'| {k} | {v} |')
    md_lines += [
        '',
        '## Notes',
        '',
        '- Replay loop builds one row per calendar date in the window,',
        '  including days with zero articles (delta remains empty, judgement',
        '  runs on the carry state).',
        '- Each date uses only articles with `date <= asof`; future rows in',
        '  `_taxonomy_remap_trace.jsonl` / `_regime_quality.jsonl` do not',
        '  influence any asof cut.',
        '- Initial state is `neutral_empty` — the live regime snapshot is',
        '  deliberately not used to avoid leaking live state into historical',
        '  backfill.',
        '- `churn_proxy` here is a day-level proxy (candidate_days includes',
        '  same calendar-day, since replay emits one row per calendar date).',
        '',
    ]
    out_md.write_text('\n'.join(md_lines), encoding='utf-8')

    return payload


# ─────────────────────────────────────────────────────────────
# CLI entry
# ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m market_research.tools.regime_replay',
        description='as-of-date regime replay (supplementary, not live).',
    )
    parser.add_argument('--start', required=True, help='YYYY-MM-DD')
    parser.add_argument('--end', required=True, help='YYYY-MM-DD')
    parser.add_argument('--lookback-days', type=int, default=DEFAULT_LOOKBACK_DAYS,
                        help=f'rolling window length (default {DEFAULT_LOOKBACK_DAYS})')
    args = parser.parse_args(argv)

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if start > end:
        print('[error] --start must be <= --end')
        return 2
    if args.lookback_days < 1:
        print('[error] --lookback-days must be >= 1')
        return 2

    payload = replay(start=start, end=end, lookback_days=args.lookback_days)
    s = payload['summary']

    print('=== regime_replay summary ===')
    print(f'mode: {payload["mode"]} — {payload["note"]}')
    print(f'window: {payload["start"]} ~ {payload["end"]}  '
          f'(lookback {payload["lookback_days"]}d, '
          f'initial_state={payload["initial_state"]})')
    print(f'total_replay_dates: {payload["total_replay_dates"]}  '
          f'unique: {payload["unique_replay_dates"]}')
    print(f'total_loaded_articles: {payload["total_loaded_articles"]:,}  '
          f'per_date_avg: {payload["per_date_avg_article_count"]}')
    print(f'runtime: {payload["runtime_seconds"]}s')
    print(f'candidate_days: {s["candidate_days"]}  '
          f'confirmed_count: {s["confirmed_count"]}  '
          f'churn: {s["churn_proxy_confirmed_over_candidate_day"]}')
    print(f'avg coverage_current: {s["avg_coverage_current"]}  '
          f'avg coverage_today: {s["avg_coverage_today_core3"]}')
    print(f'→ wrote {OUT_JSONL.name}, {OUT_JSON.name}, {OUT_MD.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
