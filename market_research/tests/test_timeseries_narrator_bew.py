# -*- coding: utf-8 -*-
"""timeseries_narrator BEW 통합 acceptance tests.

DB 접속 가능 환경에서만 의미 있음. 실패 시 self-skip.
"""
from __future__ import annotations

import re
import unittest

import pandas as pd

from market_research.report import timeseries_narrator as tn
from market_research.report.timeseries_narrator import (
    BASE_DIR,
    _BEW_TRACE,
    _bew_news_for_bm,
    _bew_windows_for_bm,
    build_debate_narrative,
    build_narrative_blocks,
)


def _drop_cache(year: int, month: int):
    fp = BASE_DIR / 'data' / 'timeseries_narratives' / f'{year}-{month:02d}.json'
    if fp.exists():
        fp.unlink()


def _build_fresh(year: int, month: int) -> str:
    """캐시 무시하고 호출 → BEW trace 가 매번 갱신되도록."""
    _drop_cache(year, month)
    return build_debate_narrative(year, month)


HEADER_RE = re.compile(r'^## 기간 내 주요 시계열 변동 \(\d{4}-\d{2}-\d{2} ~ \d{4}-\d{2}-\d{2}\)', re.M)
BM_LINE_RE = re.compile(r'^▶ [^:]+: 기간수익률 [+-]?\d+\.\d+%', re.M)
SEG_LINE_RE = re.compile(r'^  \[\d{2}/\d{2}~\d{2}/\d{2}\] [+-]?\d+\.\d+%', re.M)
EV_LINE_RE = re.compile(r'^    · "', re.M)


class NarratorBEWAcceptance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            cls.narrative = _build_fresh(2026, 3)
        except Exception as exc:
            raise unittest.SkipTest(f'narrator 실행 실패 (DB 필요?): {exc}')

    # Acceptance 1: 출력 형식/톤/섹션 구조 동일
    def test_output_format_preserved(self):
        n = self.narrative
        self.assertTrue(HEADER_RE.search(n), 'header 패턴 missing')
        self.assertGreater(len(BM_LINE_RE.findall(n)), 0, 'BM 라인 0건')
        # segment 라인 1건 이상 (BEW 또는 legacy 어디서든)
        self.assertGreater(len(SEG_LINE_RE.findall(n)), 0, 'segment 라인 0건')

    # Acceptance 2: contract 없음 fallback → legacy 재현
    def test_fallback_when_no_contract(self):
        orig = tn._load_bew_for_period
        tn._load_bew_for_period = lambda months: {'windows_by_bm': {}, 'cards_by_id': {}}
        try:
            narrative = _build_fresh(2026, 3)
            # legacy 모드 → trace 의 bew_used_bms 비어있음
            self.assertEqual(_BEW_TRACE['bew_used_bms'], [],
                             'BEW 강제 비움인데 bew_used_bms 비어있지 않음')
            # 형식은 그대로 유지
            self.assertTrue(HEADER_RE.search(narrative))
            self.assertGreater(len(BM_LINE_RE.findall(narrative)), 0)
        finally:
            tn._load_bew_for_period = orig

    # Acceptance 3: trace 기록 (BEW 사용 시)
    def test_trace_populated_on_bew_use(self):
        # build_debate_narrative(2026,3) 가 BEW 사용했는지 trace 확인
        # 단, 동일 호출을 한번 더 해서 trace가 last call로 갱신된 상태에서 검증
        try:
            _build_fresh(2026, 3)
        except Exception as exc:
            self.skipTest(f'narrator 실행 실패: {exc}')
        # 2026-03 contract 가 KOSPI/Gold 보유 — narrator daily_series에 둘 다 있으니 BEW 사용
        self.assertIn(_BEW_TRACE['year'], (2026, None))
        self.assertGreater(
            len(_BEW_TRACE['bew_used_bms']) + len(_BEW_TRACE['fallback_bms']),
            0, 'trace 비어있음')
        # 최소 1개 BM 이 BEW 경로
        self.assertGreater(len(_BEW_TRACE['bew_used_bms']), 0,
                           'BEW 사용 BM 0건 (contract 매칭 실패?)')
        # window_ids 비어있지 않음
        self.assertGreater(len(_BEW_TRACE['window_ids']), 0)

    # Acceptance 4: 호출자 인터페이스 변경 0건 (str 반환 유지)
    def test_return_type_is_str(self):
        self.assertIsInstance(self.narrative, str)
        self.assertGreater(len(self.narrative), 100)

    # Acceptance 5: 자체 z 계산 함수 dead code 화 X (legacy fallback 호출됨)
    def test_legacy_path_still_alive(self):
        # 33개 BM 중 BEW가 KOSPI/Gold만 가지므로 나머지 30+개는 _detect_segments 호출
        self.assertGreater(len(_BEW_TRACE['fallback_bms']), 0,
                           'fallback BM 0건 — legacy 경로 dead?')

    # 추가: 부분 fallback 케이스 — mock contract 로 일부 BM만 BEW 채움
    def test_partial_fallback_with_mock_contract(self):
        """mock: KOSPI는 BEW window 보유, Gold는 비움 → KOSPI=BEW / Gold=legacy."""
        mock_window = {
            'window_id': 'mock_kospi_01',
            'benchmark': 'KOSPI',
            'asset_class': '국내주식',
            'date_from': '2026-03-04',
            'date_to': '2026-03-06',
            'pivot_date': '2026-03-04',
            'signal_type': 'drawdown',
            'benchmark_move_pct': -10.5,
            'zscore': -3.2,
            'mapped_evidence_ids': ['mockid_001'],
            'confidence': 0.95,
        }
        mock_card = {
            'window_id': 'mock_kospi_01',
            'evidence_id': 'mockid_001',
            'source_type': 'naver_research',
            'date': '2026-03-04',
            'asset_class': '국내주식',
            'primary_topic': '지정학',
            'title': 'MOCK: 가짜 코스피 reasearch evidence',
            'source': 'MOCK증권',
            'salience': 0.9,
        }
        mock_data = {
            'windows_by_bm': {'KOSPI': [mock_window]},
            'cards_by_id': {'mockid_001': mock_card},
        }
        orig = tn._load_bew_for_period
        tn._load_bew_for_period = lambda months: mock_data
        try:
            narrative = _build_fresh(2026, 3)
            # KOSPI는 BEW 사용, Gold는 fallback
            self.assertIn('KOSPI', _BEW_TRACE['bew_used_bms'],
                          'KOSPI BEW 경로 미사용')
            self.assertIn('Gold', _BEW_TRACE['fallback_bms'],
                          'Gold legacy 경로 미사용')
            self.assertIn('mock_kospi_01', _BEW_TRACE['window_ids'])
            # mock evidence 가 출력에 인용되어야 함
            self.assertIn('MOCK증권', narrative,
                          'mock evidence card source 미반영')
            # 형식은 그대로
            self.assertTrue(HEADER_RE.search(narrative))
        finally:
            tn._load_bew_for_period = orig

    # 단위: helper 함수
    def test_bew_windows_for_bm_returns_segment_format(self):
        bew_data = {
            'windows_by_bm': {
                'KOSPI': [{
                    'window_id': 'w1', 'benchmark': 'KOSPI',
                    'date_from': '2026-03-04', 'date_to': '2026-03-06',
                    'signal_type': 'drawdown', 'benchmark_move_pct': -10.5,
                    'zscore': -3.2, 'confidence': 0.9,
                    'mapped_evidence_ids': ['eid1'],
                }],
            },
            'cards_by_id': {},
        }
        segs = _bew_windows_for_bm('KOSPI', bew_data)
        self.assertEqual(len(segs), 1)
        s = segs[0]
        for k in ('start_date', 'end_date', 'zscore', 'return_pct', 'direction'):
            self.assertIn(k, s)
        self.assertIsInstance(s['start_date'], pd.Timestamp)
        self.assertEqual(s['direction'], 'down')
        self.assertEqual(s['zscore'], 3.2)  # 양수
        self.assertEqual(s['_source'], 'bew')

    def test_bew_news_for_bm_returns_news_format(self):
        bew_data = {
            'windows_by_bm': {},
            'cards_by_id': {
                'eid1': {'evidence_id': 'eid1', 'title': 'T', 'source': 'S',
                         'date': '2026-03-04', 'salience': 0.8, 'source_type': 'naver_research'},
            },
        }
        seg = {'_mapped_evidence_ids': ['eid1', 'eid_missing']}
        news = _bew_news_for_bm(seg, bew_data, max_news=2)
        self.assertEqual(len(news), 1)  # missing 은 skip
        for k in ('title', 'source', 'date', 'distance'):
            self.assertIn(k, news[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
