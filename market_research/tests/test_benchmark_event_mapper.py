# -*- coding: utf-8 -*-
"""benchmark_event_mapper acceptance tests.

대상: 2026-03 (이미 mapper 실행되어 contract 파일 존재).
DB 접속이 가능한 환경에서만 의미 있음. 파일 부재 시 self-skip.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from market_research.report.benchmark_event_mapper import (
    _OUT_DIR,
    build_visualization_contract,
    detect_benchmark_windows,
    map_events_to_windows,
)


YEAR, MONTH = 2026, 3
PERIOD = f'{YEAR}-{MONTH:02d}'
CONTRACT_FP = _OUT_DIR / f'{PERIOD}.json'


class BenchmarkEventMapperAcceptance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if CONTRACT_FP.exists():
            cls.contract = json.loads(CONTRACT_FP.read_text(encoding='utf-8'))
        else:
            try:
                cls.contract = build_visualization_contract(YEAR, MONTH)
            except Exception as exc:
                raise unittest.SkipTest(f'contract 생성 실패 (DB 접속 필요?): {exc}')

    # Acceptance 1
    def test_detect_at_least_3_windows(self):
        wins = self.contract['windows']
        self.assertGreaterEqual(len(wins), 3, f'window 탐지 부족: {len(wins)}')

    # Acceptance 2
    def test_each_window_has_evidence(self):
        for w in self.contract['windows']:
            self.assertGreaterEqual(
                w['evidence_count'], 1,
                f'window {w["window_id"]} 에 evidence 0건')

    # Acceptance 3
    def test_contract_has_required_top_keys(self):
        for k in ('month', 'windows', 'timeline', 'graph', 'evidence_cards', 'debug'):
            self.assertIn(k, self.contract, f'contract 최상위 키 missing: {k}')
        self.assertEqual(self.contract['month'], PERIOD)

    # Acceptance 4
    def test_evidence_cards_required_fields(self):
        required = {'evidence_id', 'source_type', 'date', 'asset_class'}
        cards = self.contract['evidence_cards']
        self.assertGreater(len(cards), 0, 'evidence_cards 비어 있음')
        for card in cards:
            for k in required:
                self.assertIn(k, card, f'card 필드 missing: {k}')
                self.assertTrue(card[k], f'card 필드 비어있음: {k} → {card}')
            self.assertIn(card['source_type'], ('naver_research', 'news'),
                          f'source_type 값 오류: {card["source_type"]}')

    # 추가 sanity
    def test_window_quota_balance(self):
        """source mix가 quota 비율(nr 5/8 ≈ 62.5%)에서 크게 벗어나지 않음."""
        debug = self.contract['debug']
        nr = debug['source_mix']['naver_research']
        news = debug['source_mix']['news']
        total = nr + news
        if total == 0:
            self.skipTest('evidence 0건')
        nr_ratio = nr / total
        # ±15%p 허용 (window별 풀 부족 시 흡수 발생)
        self.assertGreaterEqual(nr_ratio, 0.45,
            f'nr 비율 너무 낮음: {nr_ratio:.2%}')
        self.assertLessEqual(nr_ratio, 0.85,
            f'nr 비율 너무 높음: {nr_ratio:.2%}')

    def test_timeline_sorted_by_date(self):
        dates = [t['date'] for t in self.contract['timeline']]
        self.assertEqual(dates, sorted(dates), 'timeline 날짜 정렬 안됨')

    def test_windows_have_signal_type(self):
        valid = {'anomaly', 'trend_break', 'drawdown', 'rebound'}
        for w in self.contract['windows']:
            self.assertIn(w['signal_type'], valid)

    def test_graph_edges_endpoints_in_nodes(self):
        node_ids = {n['node_id'] for n in self.contract['graph']['nodes']}
        for e in self.contract['graph']['edges']:
            self.assertIn(e['from'], node_ids,
                f'edge from 노드 missing: {e["from"]}')
            self.assertIn(e['to'], node_ids,
                f'edge to 노드 missing: {e["to"]}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
