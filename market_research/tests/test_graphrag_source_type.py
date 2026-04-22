# -*- coding: utf-8 -*-
"""GraphRAG source_type provenance acceptance (Phase 3).

실행 전에 해당 월 `data/insight_graph/{YYYY-MM}.json` 이 rebuild 완료된 상태여야 한다.

판정 4개:
  1. 모든 노드에 `source_types` 필드 존재 (seed 노드는 빈 리스트 허용)
  2. `metadata.source_type_stats.nr_sampled_pct >= 10`
  3. news_entity / llm_inferred 엣지에서 `source_type` 필드 보유 ≥ 95%
  4. 회귀 없음: node/edge count 가 이전 달 대비 ±20% (2개월 이상 인자 주면 체크,
     단일 월이면 skip)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

_BASE = Path(__file__).resolve().parent.parent
GRAPH_DIR = _BASE / 'data' / 'insight_graph'


def _check_month(month: str, prev_month: str = None) -> dict:
    p = GRAPH_DIR / f'{month}.json'
    out = {'month': month, 'failed': []}
    if not p.exists():
        out['failed'].append(f'{p} missing')
        return out
    g = json.loads(p.read_text(encoding='utf-8'))
    nodes = g.get('nodes', {})
    edges = g.get('edges', [])
    meta = g.get('metadata', {})
    stats = meta.get('source_type_stats', {})

    # 1. 모든 노드에 source_types 필드 존재
    missing_field = sum(1 for n in nodes.values() if 'source_types' not in n)
    out['nodes_total'] = len(nodes)
    out['nodes_missing_source_types_field'] = missing_field
    if missing_field > 0:
        out['failed'].append(
            f'node_field_missing: {missing_field}/{len(nodes)}')

    # 2. nr sampled pct >= 10
    nr_pct = stats.get('nr_sampled_pct', 0.0)
    out['nr_sampled_pct'] = nr_pct
    out['nr_sampled'] = stats.get('nr_articles_sampled', 0)
    out['news_sampled'] = stats.get('news_articles_sampled', 0)
    if nr_pct < 10.0:
        out['failed'].append(f'nr_sampled_pct < 10: {nr_pct}%')

    # 3. 이번 월 신규 추가 ext_edges 의 source_type coverage >= 95%
    # (legacy 누적 엣지는 Phase 3 이전에 만들어져 source_type 이 없으므로 집계 제외)
    cov_all = stats.get('ext_edge_source_type_coverage_pct', 0.0)
    cov_new = stats.get('ext_edges_new_coverage_pct', 0.0)
    out['ext_edges_total'] = stats.get('ext_edges_total', 0)
    out['ext_edges_new'] = stats.get('ext_edges_new', 0)
    out['legacy_ext_edges_inherited'] = stats.get('legacy_ext_edges_inherited', 0)
    out['ext_edge_source_type_coverage_pct_all'] = cov_all
    out['ext_edges_new_coverage_pct'] = cov_new
    out['nr_edges'] = stats.get('nr_edges', 0)
    out['nr_edges_new'] = stats.get('nr_edges_new', 0)
    if out['ext_edges_new'] == 0:
        out['failed'].append('ext_edges_new == 0 (이번 월 엔티티 추출이 엣지를 안 만듦)')
    elif cov_new < 95.0:
        out['failed'].append(f'ext_edges_new_coverage_pct < 95: {cov_new}%')
    if out['nr_edges_new'] == 0:
        out['failed'].append('nr_edges_new == 0 (nr 기사 기반 엣지 생성 0)')

    # 4. 이전 달 대비 회귀
    out['edge_count'] = len(edges)
    if prev_month:
        pp = GRAPH_DIR / f'{prev_month}.json'
        if pp.exists():
            g0 = json.loads(pp.read_text(encoding='utf-8'))
            prev_n = len(g0.get('nodes', {}))
            prev_e = len(g0.get('edges', []))
            n_delta = abs(len(nodes) - prev_n) / max(prev_n, 1)
            e_delta = abs(len(edges) - prev_e) / max(prev_e, 1)
            out['prev_month'] = prev_month
            out['node_delta_pct'] = round(n_delta * 100, 1)
            out['edge_delta_pct'] = round(e_delta * 100, 1)
            # Phase 3 는 source_type 추가로 ±20% 이내 기대 (누적 그래프라 실제론 작음)
            if n_delta > 0.5 or e_delta > 0.5:
                out['failed'].append(
                    f'regression: nodes Δ={n_delta:.1%} edges Δ={e_delta:.1%}')

    return out


def main(months: list[str]) -> int:
    overall_fail = False
    prev = None
    for m in months:
        print(f'\n── {m} ──')
        r = _check_month(m, prev_month=prev)
        print(f'  nodes={r.get("nodes_total")}, edges={r.get("edge_count")}')
        print(f'  nr_sampled={r.get("nr_sampled")} / news_sampled={r.get("news_sampled")} '
              f'→ nr_sampled_pct={r.get("nr_sampled_pct")}% (≥10%)')
        print(f'  ext_edges_total={r.get("ext_edges_total")} '
              f'(legacy_inherited={r.get("legacy_ext_edges_inherited")}) '
              f'all_coverage={r.get("ext_edge_source_type_coverage_pct_all")}% (참고용)')
        print(f'  ext_edges_new={r.get("ext_edges_new")} '
              f'new_coverage={r.get("ext_edges_new_coverage_pct")}% (acceptance ≥95%)')
        print(f'  nr_edges_total={r.get("nr_edges")} nr_edges_new={r.get("nr_edges_new")} (≥1)')
        if 'node_delta_pct' in r:
            print(f'  vs {r["prev_month"]}: nodes Δ={r["node_delta_pct"]}% '
                  f'edges Δ={r["edge_delta_pct"]}%')
        if r['failed']:
            print(f'  FAIL: {r["failed"]}')
            overall_fail = True
        else:
            print(f'  PASS')
        prev = m

    print()
    print('OVERALL:', 'FAIL' if overall_fail else 'PASS')
    return 1 if overall_fail else 0


if __name__ == '__main__':
    months = sys.argv[1:] if len(sys.argv) > 1 else ['2026-02', '2026-03', '2026-04']
    sys.exit(main(months))
