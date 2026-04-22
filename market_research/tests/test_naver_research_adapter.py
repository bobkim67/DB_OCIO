# -*- coding: utf-8 -*-
"""
naver_research_adapter 유닛 테스트 — Phase 2.

검증 범위:
  - to_article_like: raw → article-like 스키마 매핑
  - apply_research_quality_heuristic: TIER band 결정 로직
  - build/save/load round-trip
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from market_research.collect import naver_research_adapter as A


def _raw(**overrides) -> dict:
    base = {
        'title': '테스트 리포트',
        'date': '2026-01-15',
        'broker': '테스트증권',
        'broker_source': 'list',
        'category': 'economy',
        'nid': 12345,
        'dedupe_key': 'economy:12345',
        'detail_url': 'https://finance.naver.com/research/economy_read.naver?nid=12345',
        'summary_text': '거시경제 전망 요약 본문 ' * 20,  # ~240자
        'summary_char_len': 240,
        'has_pdf': True,
        'pdf_bytes': 500_000,
        '_warnings': [],
        'collector_version': '0.2.0',
        'source_type': 'naver_research',
    }
    base.update(overrides)
    return base


class TestToArticleLike(unittest.TestCase):

    def test_basic_schema_mapping(self):
        art = A.to_article_like(_raw())
        self.assertEqual(art['title'], '테스트 리포트')
        self.assertEqual(art['date'], '2026-01-15')
        self.assertEqual(art['source'], '테스트증권')
        self.assertEqual(art['source_type'], 'naver_research')
        self.assertTrue(art['url'].startswith('https://finance.naver.com/'))
        self.assertEqual(art['_raw_category'], 'economy')
        self.assertEqual(art['_raw_nid'], 12345)
        self.assertEqual(art['_raw_dedupe_key'], 'economy:12345')

    def test_source_fallback_to_category(self):
        """broker 비어있으면 category를 source로."""
        art = A.to_article_like(_raw(broker=''))
        self.assertEqual(art['source'], 'economy')

    def test_description_from_summary_text(self):
        art = A.to_article_like(_raw(summary_text='요약문'))
        self.assertEqual(art['description'], '요약문')

    def test_raw_warnings_preserved(self):
        art = A.to_article_like(_raw(_warnings=['empty_summary', 'broker_missing']))
        self.assertIn('empty_summary', art['_raw_warnings'])
        self.assertIn('broker_missing', art['_raw_warnings'])


class TestQualityHeuristic(unittest.TestCase):

    def test_economy_becomes_tier1(self):
        art = A.to_article_like(_raw(category='economy'))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER1')
        self.assertIn('category_tier1', art['_adapter_flags'])

    def test_industry_is_tier1(self):
        art = A.to_article_like(_raw(category='industry'))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER1')

    def test_debenture_is_tier1(self):
        art = A.to_article_like(_raw(category='debenture'))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER1')

    def test_market_info_base_tier2(self):
        art = A.to_article_like(_raw(category='market_info', has_pdf=False, pdf_bytes=None))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER2')

    def test_invest_base_tier2(self):
        art = A.to_article_like(_raw(category='invest', has_pdf=False, pdf_bytes=None))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER2')

    def test_short_summary_forces_tier3(self):
        """summary_char_len < 120 → TIER3 강등."""
        art = A.to_article_like(_raw(category='economy', summary_char_len=80, summary_text='짧은요약'))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER3')
        self.assertIn('short_summary', art['_adapter_flags'])

    def test_pdf_rich_tier_up_tier2_to_tier1(self):
        """TIER2 카테고리라도 PDF bytes 크면 TIER1으로 승격."""
        art = A.to_article_like(_raw(
            category='invest', has_pdf=True, pdf_bytes=500_000, summary_char_len=200,
        ))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER1')
        self.assertIn('pdf_rich', art['_adapter_flags'])

    def test_raw_warning_downgrades_tier1(self):
        """economy + empty_summary warning → TIER2."""
        art = A.to_article_like(_raw(
            category='economy', summary_char_len=200,
            _warnings=['empty_summary'],
        ))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER2')
        self.assertIn('raw_warning_downgrade', art['_adapter_flags'])

    def test_broker_missing_mild_downgrade(self):
        """TIER1 + broker_missing → TIER2 소폭 하향."""
        art = A.to_article_like(_raw(
            category='economy', summary_char_len=200, broker='',
            _warnings=['broker_missing'],
        ))
        A.apply_research_quality_heuristic(art)
        self.assertEqual(art['_research_quality_band'], 'TIER2')
        self.assertIn('missing_broker', art['_adapter_flags'])

    def test_score_matches_band(self):
        for band, expected in [('TIER1', 1.0), ('TIER2', 0.7), ('TIER3', 0.3)]:
            # 조건 구성
            if band == 'TIER1':
                art = A.to_article_like(_raw(category='economy', summary_char_len=200))
            elif band == 'TIER2':
                art = A.to_article_like(_raw(category='invest', summary_char_len=200, has_pdf=False, pdf_bytes=None))
            else:
                art = A.to_article_like(_raw(summary_char_len=50))
            A.apply_research_quality_heuristic(art)
            self.assertEqual(art['_research_quality_band'], band)
            self.assertEqual(art['_research_quality_score'], expected)

    def test_empty_description_flagged(self):
        art = A.to_article_like(_raw(summary_text='', summary_char_len=200))
        A.apply_research_quality_heuristic(art)
        self.assertIn('empty_description', art['_adapter_flags'])


class TestBuildAndRoundTrip(unittest.TestCase):

    def test_save_load_round_trip(self):
        articles = [
            A.apply_research_quality_heuristic(A.to_article_like(_raw(nid=1, dedupe_key='economy:1'))),
            A.apply_research_quality_heuristic(A.to_article_like(_raw(nid=2, dedupe_key='economy:2', category='invest'))),
        ]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(A, 'ADAPTED_DIR', Path(td)):
                p = A.save_adapted('2026-01', articles)
                self.assertTrue(p.exists())
                loaded = A.load_adapted('2026-01')
                self.assertEqual(len(loaded), 2)
                self.assertEqual(loaded[0]['_raw_nid'], 1)
                self.assertEqual(loaded[1]['_raw_category'], 'invest')

    def test_load_nonexistent_month_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(A, 'ADAPTED_DIR', Path(td)):
                self.assertEqual(A.load_adapted('1999-01'), [])


if __name__ == '__main__':
    unittest.main()
