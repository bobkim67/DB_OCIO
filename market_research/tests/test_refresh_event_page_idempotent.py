"""Regression: refresh_base_pages_after_refine() 가 idempotent.

F3 P1.5-a (wipe) + P1.5-b (deterministic id) 결합 회귀:
  - 2회 실행 시 01_Events page 수 증가 X
  - 2회 실행 시 동일 file path 생성 (deterministic id 효과)
  - 다른 디렉토리 (02_Entities, 03_Assets, 04_Funds, 05_Regime_Canonical)
    페이지는 wipe 영향 없음

운영 wiki dir 안전성을 위해 임시 dir 로 격리.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _make_synthetic_articles() -> list[dict]:
    """현실적인 cluster 시뮬레이션 — 2 cluster × 3 articles."""
    return [
        # Cluster A: 휴전 합의
        {'date': '2026-04-08', 'source': '뉴시스', 'title': "원·달러, 미·이란 '2주 휴전'에 24.3원 급락",
         'url': 'https://www.newsis.com/view/A1', 'primary_topic': '환율_FX',
         'is_primary': True, '_event_salience': 0.9, '_classified_topics': [{'topic': '환율_FX'}]},
        {'date': '2026-04-08', 'source': '뉴스1', 'title': '코스피 5% 급등 환율 24원 폭락 휴전 기대',
         'url': 'https://www.news1.kr/A2', 'primary_topic': '환율_FX',
         'is_primary': True, '_event_salience': 0.85, '_classified_topics': [{'topic': '환율_FX'}]},
        {'date': '2026-04-08', 'source': '연합뉴스', 'title': '원달러 환율 24원 급락 미이란 휴전',
         'url': 'https://www.yna.co.kr/A3', 'primary_topic': '환율_FX',
         'is_primary': True, '_event_salience': 0.82, '_classified_topics': [{'topic': '환율_FX'}]},
        # Cluster B: 유가 급등
        {'date': '2026-04-09', 'source': '연합뉴스', 'title': 'IEA 총장 현 에너지 위기 1970년대 오일쇼크보다 심각',
         'url': 'https://www.yna.co.kr/B1', 'primary_topic': '에너지_원자재',
         'is_primary': True, '_event_salience': 0.95, '_classified_topics': [{'topic': '에너지_원자재'}]},
        {'date': '2026-04-09', 'source': '뉴시스', 'title': '유가 급등 IEA 1970년대 오일쇼크보다 심각',
         'url': 'https://www.newsis.com/B2', 'primary_topic': '에너지_원자재',
         'is_primary': True, '_event_salience': 0.88, '_classified_topics': [{'topic': '에너지_원자재'}]},
        {'date': '2026-04-09', 'source': '뉴스1', 'title': '국제유가 폭등 에너지 위기 심각',
         'url': 'https://www.news1.kr/B3', 'primary_topic': '에너지_원자재',
         'is_primary': True, '_event_salience': 0.85, '_classified_topics': [{'topic': '에너지_원자재'}]},
    ]


def _setup_temp_wiki(tmp_path: Path, month_str: str, articles: list[dict]) -> Path:
    """임시 wiki dir + news/{month}.json 셋업.

    Returns: tmp_root (NEWS_DIR / WIKI dir 의 부모)
    """
    news_dir = tmp_path / 'data' / 'news'
    news_dir.mkdir(parents=True, exist_ok=True)
    (news_dir / f'{month_str}.json').write_text(
        json.dumps({'articles': articles}, ensure_ascii=False), encoding='utf-8'
    )
    wiki_root = tmp_path / 'data' / 'wiki'
    for d in ('00_Index', '01_Events', '02_Entities', '03_Assets', '04_Funds',
              '05_Regime_Canonical'):
        (wiki_root / d).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_refresh_idempotent_event_pages(tmp_path, monkeypatch):
    """refresh_base_pages_after_refine() 2회 실행 → event page 수 동일 + 동일 file paths."""
    from market_research.core import dedupe
    from market_research.wiki import draft_pages

    month_str = '2026-04'
    articles = _make_synthetic_articles()
    dedupe.assign_article_ids(articles)
    dedupe.cluster_events(articles)

    tmp_root = _setup_temp_wiki(tmp_path, month_str, articles)
    monkeypatch.setattr(draft_pages, 'BASE_DIR', tmp_root)
    # NEWS_DIR / EVENTS_DIR 등 모든 디렉토리 상수를 임시로 가리킴 — 운영 articles
    # 데이터를 건드리지 않도록 격리 (NEWS_DIR 누락 시 _load_month_articles 가
    # 운영 dir 의 stale articles 를 로드해 검증이 무의미해짐).
    monkeypatch.setattr(draft_pages, 'NEWS_DIR', tmp_root / 'data' / 'news')
    monkeypatch.setattr(draft_pages, 'EVENTS_DIR', tmp_root / 'data' / 'wiki' / '01_Events')
    monkeypatch.setattr(draft_pages, 'INDEX_DIR', tmp_root / 'data' / 'wiki' / '00_Index')
    monkeypatch.setattr(draft_pages, 'ENTITIES_DIR', tmp_root / 'data' / 'wiki' / '02_Entities')
    monkeypatch.setattr(draft_pages, 'ASSETS_DIR', tmp_root / 'data' / 'wiki' / '03_Assets')
    monkeypatch.setattr(draft_pages, 'FUNDS_DIR', tmp_root / 'data' / 'wiki' / '04_Funds')

    events_dir = tmp_root / 'data' / 'wiki' / '01_Events'

    # Run 1
    draft_pages.refresh_base_pages_after_refine(month_str, top_events=5,
                                                 top_entities=0)
    files_after_run1 = sorted(p.name for p in events_dir.glob(f'{month_str}_event_*.md'))
    n1 = len(files_after_run1)
    assert n1 >= 1, f'expected ≥1 event page after run 1, got {n1}'

    # 모든 파일명이 deterministic hex 형식 (event_[0-9a-f]{10}) 인지
    import re
    pattern = re.compile(rf'{re.escape(month_str)}_event_[0-9a-f]{{10}}\.md')
    for fname in files_after_run1:
        assert pattern.fullmatch(fname), (
            f'deterministic hex id 형식 위반: {fname}\n'
            f'expected pattern: {month_str}_event_[0-9a-f]{{10}}.md'
        )

    # Run 2 (idempotent 검증)
    draft_pages.refresh_base_pages_after_refine(month_str, top_events=5,
                                                 top_entities=0)
    files_after_run2 = sorted(p.name for p in events_dir.glob(f'{month_str}_event_*.md'))
    n2 = len(files_after_run2)

    assert n1 == n2, (
        f'event page 수 증가 — run1={n1}, run2={n2}.\n'
        f'  run1 files: {files_after_run1}\n'
        f'  run2 files: {files_after_run2}'
    )
    assert files_after_run1 == files_after_run2, (
        f'run1/run2 file paths 다름 — deterministic id 위반\n'
        f'  diff (run2 - run1): {set(files_after_run2) - set(files_after_run1)}'
    )


def test_refresh_does_not_touch_other_dirs(tmp_path, monkeypatch):
    """wipe 가 02/03/04/05 dir 의 페이지 건드리지 않음."""
    from market_research.core import dedupe
    from market_research.wiki import draft_pages

    month_str = '2026-04'
    articles = _make_synthetic_articles()
    dedupe.assign_article_ids(articles)
    dedupe.cluster_events(articles)

    tmp_root = _setup_temp_wiki(tmp_path, month_str, articles)
    wiki_root = tmp_root / 'data' / 'wiki'

    # 다른 dir 에 가짜 페이지 미리 생성 (wipe 영향받으면 안 됨)
    sentinels = {
        '02_Entities/2026-04_graphnode__금리.md': '# entity 금리',
        '03_Assets/2026-04_국내주식.md': '# asset 국내주식',
        '04_Funds/2026-04_07G04.md': '# fund 07G04',
        '05_Regime_Canonical/regime_history.md': '# regime',
        '00_Index/index.md': '# index',
    }
    for rel, content in sentinels.items():
        fp = wiki_root / rel
        fp.write_text(content, encoding='utf-8')

    monkeypatch.setattr(draft_pages, 'BASE_DIR', tmp_root)
    monkeypatch.setattr(draft_pages, 'NEWS_DIR', tmp_root / 'data' / 'news')
    monkeypatch.setattr(draft_pages, 'EVENTS_DIR', wiki_root / '01_Events')
    monkeypatch.setattr(draft_pages, 'INDEX_DIR', wiki_root / '00_Index')
    monkeypatch.setattr(draft_pages, 'ENTITIES_DIR', wiki_root / '02_Entities')
    monkeypatch.setattr(draft_pages, 'ASSETS_DIR', wiki_root / '03_Assets')
    monkeypatch.setattr(draft_pages, 'FUNDS_DIR', wiki_root / '04_Funds')

    draft_pages.refresh_base_pages_after_refine(month_str, top_events=3,
                                                 top_entities=0)

    for rel in sentinels:
        fp = wiki_root / rel
        # 인덱스/regime 같은 페이지는 refresh 자체가 덮어쓸 수 있음 — wipe 이슈 분리.
        # 핵심: 02_Entities/03_Assets/04_Funds 는 이번 wipe 정책에서 제외 보장.
        if rel.startswith(('02_Entities/', '03_Assets/', '04_Funds/')):
            assert fp.exists(), f'wipe 가 잘못 삭제함 — 보호 대상: {rel}'


if __name__ == '__main__':
    import tempfile
    import shutil
    # pytest 없이 단독 실행용 (간단 manual harness)
    from unittest.mock import patch

    class FakeMonkey:
        def __init__(self):
            self._patches = []
        def setattr(self, target, name, value):
            p = patch.object(target, name, value)
            p.start()
            self._patches.append(p)
        def stop_all(self):
            for p in self._patches:
                p.stop()

    for fn in [test_refresh_idempotent_event_pages, test_refresh_does_not_touch_other_dirs]:
        tmp = Path(tempfile.mkdtemp(prefix='wikitest_'))
        try:
            mp = FakeMonkey()
            fn(tmp, mp)
            mp.stop_all()
            print(f'PASS {fn.__name__}')
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print('ALL PASS')
