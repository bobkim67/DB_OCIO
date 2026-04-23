# -*- coding: utf-8 -*-
"""Forced-BEW export/load + debate_engine filter acceptance tests.

대상 기능:
  1) tabs/benchmark_event_viewer._export_forced_windows (viewer → JSON)
  2) market_research/report/cli._load_forced_bew_json (JSON → set + strict validation)
  3) market_research/report/debate_engine._build_evidence_candidates
     with force_window_ids (BEW lane filter)

테스트 데이터: 2026-03 BEW contract (기존 benchmark_event_mapper 산출물).
contract 파일 부재 시 self-skip.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

# tabs/ import 가능하도록 프로젝트 루트 sys.path 추가
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


YEAR, MONTH = 2026, 3
PERIOD = f'{YEAR}-{MONTH:02d}'
CONTRACT_FP = (PROJECT_ROOT / 'market_research' / 'data' /
               'benchmark_events' / f'{PERIOD}.json')


def _load_contract_or_skip():
    if not CONTRACT_FP.exists():
        raise unittest.SkipTest(f'BEW contract 없음: {CONTRACT_FP}')
    return json.loads(CONTRACT_FP.read_text(encoding='utf-8'))


# =================================================================
# A. debate_engine._build_evidence_candidates filter
# =================================================================

class DebateEngineForcedFilter(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.contract = _load_contract_or_skip()
        cls.all_wids = [w.get('window_id') for w in cls.contract.get('windows', [])
                        if w.get('window_id')]
        if len(cls.all_wids) < 2:
            raise unittest.SkipTest('contract 에 window 2개 미만')

    def _invoke(self, force_window_ids):
        """_build_evidence_candidates 호출 래퍼.

        adapted/news pool 로드 실패 시 빈 리스트 반환하는 설계라 환경 의존 없음.
        """
        from market_research.report.debate_engine import _build_evidence_candidates
        return _build_evidence_candidates(
            YEAR, MONTH, target_count=15, start_idx=1,
            force_window_ids=force_window_ids,
        )

    # A-1: None 이면 forced 비활성 (기존 동작)
    def test_none_no_filter(self):
        _, _, _, dbg = self._invoke(None)
        self.assertFalse(dbg.get('bew_forced_applied'))
        self.assertEqual(dbg.get('bew_forced_window_ids'), [])
        self.assertEqual(dbg.get('bew_forced_windows_kept'), 0)
        self.assertEqual(dbg.get('bew_forced_invalid_window_ids'), [])

    # A-2: 유효한 subset 만 주면 해당 wid 만 kept, 나머지 drop
    def test_valid_subset_kept(self):
        subset = set(self.all_wids[:1])
        _, _, _, dbg = self._invoke(subset)
        self.assertTrue(dbg.get('bew_forced_applied'))
        self.assertEqual(set(dbg.get('bew_forced_window_ids')), subset)
        self.assertEqual(dbg.get('bew_forced_windows_kept'), len(subset))
        self.assertEqual(dbg.get('bew_forced_invalid_window_ids'), [])

    # A-3: 일부만 유효 — invalid 는 drop 되고 valid 만 kept
    def test_partial_valid(self):
        mix = {self.all_wids[0], 'wid_does_not_exist_xxxx'}
        _, _, _, dbg = self._invoke(mix)
        self.assertTrue(dbg.get('bew_forced_applied'))
        self.assertEqual(set(dbg.get('bew_forced_window_ids')), mix)
        self.assertEqual(dbg.get('bew_forced_windows_kept'), 1)
        self.assertIn('wid_does_not_exist_xxxx',
                      dbg.get('bew_forced_invalid_window_ids', []))

    # A-4: 전부 invalid → forced_applied=True, windows_kept=0
    #      (상위 레이어 CLI 가 이 케이스를 미리 strict fail 하도록 계약됨)
    def test_all_invalid(self):
        bad = {'zzz_nope_1', 'zzz_nope_2'}
        _, _, _, dbg = self._invoke(bad)
        self.assertTrue(dbg.get('bew_forced_applied'))
        self.assertEqual(dbg.get('bew_forced_windows_kept'), 0)
        self.assertEqual(set(dbg.get('bew_forced_invalid_window_ids')), bad)


# =================================================================
# B. Viewer export_forced_windows
# =================================================================

class ViewerExportForcedWindows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.contract = _load_contract_or_skip()
        cls.all_wids = [w.get('window_id') for w in cls.contract.get('windows', [])
                        if w.get('window_id')]
        if len(cls.all_wids) < 1:
            raise unittest.SkipTest('contract 에 window 없음')

    def setUp(self):
        # export 경로 충돌 방지 — 테스트 전용 임시 dir
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        from tabs import benchmark_event_viewer as viewer_mod
        self._orig_export_dir = viewer_mod._EXPORT_DIR
        viewer_mod._EXPORT_DIR = Path(self._tmp.name)
        self.viewer_mod = viewer_mod

    def tearDown(self):
        self.viewer_mod._EXPORT_DIR = self._orig_export_dir
        self._tmp.cleanup()

    # B-1: 유효 wid 만 저장
    def test_export_valid_only(self):
        wids = [self.all_wids[0], 'invalid_xxx']
        fp, diag = self.viewer_mod._export_forced_windows(
            PERIOD, self.contract, wids, focus_wid=self.all_wids[0])
        self.assertIsNotNone(fp)
        self.assertTrue(fp.exists())
        payload = json.loads(fp.read_text(encoding='utf-8'))
        self.assertEqual(payload['schema_version'], 1)
        self.assertEqual(payload['year'], YEAR)
        self.assertEqual(payload['month'], MONTH)
        self.assertEqual(payload['force_window_ids'], [self.all_wids[0]])
        self.assertEqual(payload['source'], 'bew_viewer')
        self.assertIn('invalid_xxx', diag['invalid'])

    # B-2: 유효 wid 0건이면 파일 미작성
    def test_no_valid_skips_write(self):
        fp, diag = self.viewer_mod._export_forced_windows(
            PERIOD, self.contract, ['bad_a', 'bad_b'], focus_wid=None)
        self.assertIsNone(fp)
        self.assertEqual(diag['valid'], 0)
        self.assertEqual(diag['requested'], 2)


# =================================================================
# C. CLI _load_forced_bew_json strict validation
# =================================================================

class CliLoadForcedBewJson(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.contract = _load_contract_or_skip()
        cls.all_wids = [w.get('window_id') for w in cls.contract.get('windows', [])
                        if w.get('window_id')]
        if not cls.all_wids:
            raise unittest.SkipTest('contract 에 window 없음')

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, payload):
        fp = self.tmp_path / 'export.json'
        fp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        return fp

    def _valid_payload(self):
        return {
            'schema_version': 1,
            'year': YEAR,
            'month': MONTH,
            'force_window_ids': [self.all_wids[0]],
            'focus_window_id': self.all_wids[0],
            'exported_at': '2026-04-23T00:00:00',
            'source': 'bew_viewer',
        }

    # C-1: 정상 케이스 — set 반환
    def test_valid(self):
        from market_research.report.cli import _load_forced_bew_json
        fp = self._write(self._valid_payload())
        result = _load_forced_bew_json(str(fp), YEAR, MONTH)
        self.assertIsInstance(result, set)
        self.assertEqual(result, {self.all_wids[0]})

    # C-2: month mismatch → SystemExit
    def test_month_mismatch(self):
        from market_research.report.cli import _load_forced_bew_json
        p = self._valid_payload()
        p['month'] = MONTH + 1 if MONTH < 12 else 1
        fp = self._write(p)
        with self.assertRaises(SystemExit) as ctx:
            _load_forced_bew_json(str(fp), YEAR, MONTH)
        self.assertIn('period mismatch', str(ctx.exception))

    # C-3: schema_version != 1 → SystemExit
    def test_schema_version_mismatch(self):
        from market_research.report.cli import _load_forced_bew_json
        p = self._valid_payload()
        p['schema_version'] = 2
        fp = self._write(p)
        with self.assertRaises(SystemExit) as ctx:
            _load_forced_bew_json(str(fp), YEAR, MONTH)
        self.assertIn('schema_version', str(ctx.exception))

    # C-4: wid 전부 invalid → SystemExit
    def test_all_invalid_wids(self):
        from market_research.report.cli import _load_forced_bew_json
        p = self._valid_payload()
        p['force_window_ids'] = ['zzz_nope_1', 'zzz_nope_2']
        fp = self._write(p)
        with self.assertRaises(SystemExit) as ctx:
            _load_forced_bew_json(str(fp), YEAR, MONTH)
        self.assertIn('유효한', str(ctx.exception))

    # C-5: force_window_ids 가 list 가 아님 → SystemExit
    def test_force_window_ids_not_list(self):
        from market_research.report.cli import _load_forced_bew_json
        p = self._valid_payload()
        p['force_window_ids'] = 'not-a-list'
        fp = self._write(p)
        with self.assertRaises(SystemExit) as ctx:
            _load_forced_bew_json(str(fp), YEAR, MONTH)
        self.assertIn('force_window_ids', str(ctx.exception))

    # C-6: 파일 없음 → SystemExit
    def test_missing_file(self):
        from market_research.report.cli import _load_forced_bew_json
        with self.assertRaises(SystemExit) as ctx:
            _load_forced_bew_json(str(self.tmp_path / 'nope.json'), YEAR, MONTH)
        self.assertIn('파일 없음', str(ctx.exception))


if __name__ == '__main__':
    unittest.main(verbosity=2)
