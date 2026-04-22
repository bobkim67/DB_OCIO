"""evidence quota dry-run: _build_evidence_candidates만 호출 (LLM 없음).

결과를 debate_logs/{YYYY-MM}.json 의 `_quota_dryruns` 리스트에 append.
기존 `result` / `llm_calls` 는 건드리지 않음.

usage:
    python -m market_research.tools.quota_dryrun 2026-02
    python -m market_research.tools.quota_dryrun 2026-02 2026-03 2026-04
    python -m market_research.tools.quota_dryrun 2026-02 --target 15
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from market_research.report.debate_engine import (
    DEBATE_LOG_DIR,
    _build_evidence_candidates,
)


def _run_one(period: str, target: int) -> dict:
    year, month = (int(x) for x in period.split('-'))
    high_impact, evidence_ids, _card_lines, debug = _build_evidence_candidates(
        year=year, month=month, target_count=target, start_idx=1,
    )

    nr_picked = sum(1 for a in high_impact if a.get('source_type') == 'naver_research')
    news_picked = len(high_impact) - nr_picked
    topics = sorted({a.get('primary_topic', '') for a in high_impact if a.get('primary_topic')})

    entry = {
        'event': 'evidence_selection',
        'mode': 'dryrun',
        'ran_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'month': period,
        **debug,
        'nr_picked_verify': nr_picked,
        'news_picked_verify': news_picked,
        'topics_picked': topics,
        'evidence_ids_count': len(evidence_ids),
    }

    log_file = DEBATE_LOG_DIR / f'{period}.json'
    if log_file.exists():
        payload = json.loads(log_file.read_text(encoding='utf-8'))
    else:
        payload = {}
    runs = payload.get('_quota_dryruns', [])
    runs.append(entry)
    payload['_quota_dryruns'] = runs
    log_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding='utf-8',
    )
    print(
        f'[{period}] target={debug["target_count"]} '
        f'nr={debug["research_picked"]}/{debug["research_quota"]} '
        f'news={debug["news_picked"]}/{debug["news_quota"]} '
        f'(pool nr={debug["research_pool_size"]} news={debug["news_pool_size"]}) '
        f'topics={len(topics)} → {log_file.name}'
    )
    return entry


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Evidence quota dry-run')
    ap.add_argument('months', nargs='+', help='YYYY-MM (1개 이상)')
    ap.add_argument('--target', type=int, default=15, help='target_count (기본 15)')
    args = ap.parse_args(argv)

    for m in args.months:
        try:
            _run_one(m, args.target)
        except Exception as exc:
            print(f'[{m}] 실패: {exc}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
