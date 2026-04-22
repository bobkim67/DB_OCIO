"""evidence quota monitor: debate_logs를 스캔해서 nr/news 비율 + quota 편차 리포트.

소스 (한 파일에서 둘 다 수집):
  - 실 debate: payload['llm_calls'][i] where event == 'evidence_selection'
  - dry-run:   payload['_quota_dryruns'][i]

판정: research_picked / total_picked 가 RESEARCH_QUOTA ±TOLERANCE 안이면 PASS.

usage:
    python -m market_research.tools.quota_monitor
    python -m market_research.tools.quota_monitor --tolerance 0.10
    python -m market_research.tools.quota_monitor --jsonl out.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from market_research.report.debate_engine import DEBATE_LOG_DIR, RESEARCH_QUOTA


def _iter_logs(log_dir: Path):
    for fp in sorted(log_dir.glob('*.json')):
        try:
            payload = json.loads(fp.read_text(encoding='utf-8'))
        except Exception as exc:
            print(f'[skip] {fp.name}: {exc}', file=sys.stderr)
            continue
        if not isinstance(payload, dict):
            continue
        # 실 debate
        for call in payload.get('llm_calls', []) or []:
            if call.get('event') == 'evidence_selection':
                yield fp.stem, 'live', call
        # dry-run
        for run in payload.get('_quota_dryruns', []) or []:
            yield fp.stem, 'dryrun', run


def _summarize(entry: dict, tol: float) -> dict:
    target = int(entry.get('target_count') or 0)
    rp = int(entry.get('research_picked') or 0)
    np_ = int(entry.get('news_picked') or 0)
    total = int(entry.get('total_picked') or (rp + np_))
    nr_pct = (rp / total) if total else 0.0
    deviation = nr_pct - RESEARCH_QUOTA
    passed = abs(deviation) <= tol and total > 0
    return {
        'target': target,
        'research_quota': int(entry.get('research_quota') or 0),
        'news_quota': int(entry.get('news_quota') or 0),
        'research_pool_size': int(entry.get('research_pool_size') or 0),
        'news_pool_size': int(entry.get('news_pool_size') or 0),
        'research_picked': rp,
        'news_picked': np_,
        'total_picked': total,
        'nr_pct': nr_pct,
        'deviation': deviation,
        'passed': passed,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Evidence quota monitor')
    ap.add_argument('--tolerance', type=float, default=0.10,
                    help='허용 편차 (기본 0.10 = ±10%%p)')
    ap.add_argument('--jsonl', type=Path, default=None,
                    help='집계 결과를 JSONL로 저장 (옵션)')
    ap.add_argument('--log-dir', type=Path, default=DEBATE_LOG_DIR,
                    help='debate_logs 디렉토리 (기본: data/debate_logs)')
    args = ap.parse_args(argv)

    rows = []
    for stem, mode, entry in _iter_logs(args.log_dir):
        s = _summarize(entry, args.tolerance)
        s['file_period'] = stem
        s['entry_month'] = entry.get('month', stem)
        s['mode'] = mode
        s['ts'] = entry.get('ran_at') or entry.get('ts', '')
        rows.append(s)

    if not rows:
        print('(evidence_selection 항목 없음)')
        return 0

    # 출력 표
    target_pct = RESEARCH_QUOTA * 100
    tol_pct = args.tolerance * 100
    print(f'\n=== Evidence Quota Monitor (target nr={target_pct:.0f}% ±{tol_pct:.0f}%p) ===')
    header = (
        f'{"file":<10} {"month":<10} {"mode":<7} '
        f'{"nr":>4} {"news":>5} {"tot":>4} '
        f'{"nr%":>6} {"dev":>7} {"pool nr":>8} {"pool news":>10} {"pass":>5}'
    )
    print(header)
    print('-' * len(header))
    n_pass = n_fail = 0
    for r in rows:
        flag = 'PASS' if r['passed'] else 'FAIL'
        if r['passed']:
            n_pass += 1
        else:
            n_fail += 1
        print(
            f'{r["file_period"]:<10} {r["entry_month"]:<10} {r["mode"]:<7} '
            f'{r["research_picked"]:>4} {r["news_picked"]:>5} {r["total_picked"]:>4} '
            f'{r["nr_pct"]*100:>5.1f}% {r["deviation"]*100:>+6.1f}% '
            f'{r["research_pool_size"]:>8} {r["news_pool_size"]:>10} {flag:>5}'
        )
    print('-' * len(header))
    print(f'  total entries: {len(rows)}  pass: {n_pass}  fail: {n_fail}')

    if args.jsonl:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        with args.jsonl.open('w', encoding='utf-8') as fp:
            for r in rows:
                fp.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f'  → {args.jsonl}')

    return 0 if n_fail == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
