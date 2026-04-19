# -*- coding: utf-8 -*-
"""P0 vs P1 비교 리포트 — transmission path 지표.

사용:
    python -m market_research.tests.test_graphrag_p0_vs_p1 2026-04
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def run(period: str = '2026-04') -> dict:
    from market_research.analyze.graph_rag import precompute_transmission_paths
    from market_research.analyze.graph_vocab import DRIVER_TAXONOMY, ASSET_TAXONOMY

    base = Path(__file__).resolve().parent.parent
    gfile = base / 'data' / 'insight_graph' / f'{period}.json'
    if not gfile.exists():
        raise FileNotFoundError(gfile)
    g = json.loads(gfile.read_text(encoding='utf-8'))

    # P0
    p0 = precompute_transmission_paths(g, quality_log_path=None, phase='P0')
    # P1
    p1 = precompute_transmission_paths(g, quality_log_path=None, phase='P1')

    def _summary(paths, trig_total, tgt_total):
        trigs = {p['trigger'] for p in paths}
        tgts = {p['target'] for p in paths}
        return {
            'total_paths': len(paths),
            'unique_triggers': len(trigs),
            'unique_targets': len(tgts),
            'trig_total': trig_total,
            'tgt_total': tgt_total,
            'unmatched_triggers': trig_total - len(trigs),
            'unmatched_targets': tgt_total - len(tgts),
            'avg_confidence': round(
                sum(p.get('confidence', 0) for p in paths) / len(paths), 3
            ) if paths else 0,
            'top_3': [
                {
                    'trigger': p['trigger'],
                    'target': p['target'],
                    'confidence': p['confidence'],
                    'path': ' → '.join(p.get('path_labels') or p.get('path', [])),
                }
                for p in sorted(paths, key=lambda x: -x.get('confidence', 0))[:3]
            ],
        }

    p0_sum = _summary(p0, 9, 12)   # legacy 9 triggers / 12 targets
    p1_sum = _summary(p1, len(DRIVER_TAXONOMY), len(ASSET_TAXONOMY))

    print(f'\n=== GraphRAG P0 vs P1 비교 — {period} ===\n')
    print(f'{"metric":<22} {"P0":>10} {"P1":>10}  해석')
    print('-' * 70)
    for key, label, interp in [
        ('total_paths', 'total_paths', '경로 수'),
        ('unique_triggers', 'unique_triggers', '활성 trigger'),
        ('unique_targets', 'unique_targets', '활성 target'),
        ('unmatched_triggers', 'unmatched_triggers', '미활성 trigger'),
        ('unmatched_targets', 'unmatched_targets', '미활성 target'),
        ('avg_confidence', 'avg_confidence', '평균 신뢰도'),
    ]:
        print(f'{label:<22} {p0_sum[key]:>10} {p1_sum[key]:>10}  {interp}')

    print(f'\nTrigger coverage: P0 {p0_sum["unique_triggers"]}/{p0_sum["trig_total"]} → '
          f'P1 {p1_sum["unique_triggers"]}/{p1_sum["trig_total"]}')
    print(f'Target coverage : P0 {p0_sum["unique_targets"]}/{p0_sum["tgt_total"]} → '
          f'P1 {p1_sum["unique_targets"]}/{p1_sum["tgt_total"]}')

    print(f'\n--- P0 top 3 paths ---')
    for r in p0_sum['top_3']:
        print(f'  {r["trigger"]} → {r["target"]} (conf={r["confidence"]:.3f}): {r["path"]}')
    print(f'\n--- P1 top 3 paths ---')
    for r in p1_sum['top_3']:
        print(f'  {r["trigger"]} → {r["target"]} (conf={r["confidence"]:.3f}): {r["path"]}')

    return {'P0': p0_sum, 'P1': p1_sum}


if __name__ == '__main__':
    period = sys.argv[1] if len(sys.argv) > 1 else '2026-04'
    run(period)
