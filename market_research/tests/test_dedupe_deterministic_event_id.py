"""Regression: dedupe.cluster_events() 의 _event_group_id 가 deterministic.

F3 P1.5-b (2026-05-06):
  이전 구현은 'event_{counter}' sequential id 였음 → articles 입력 순서가
  바뀌면 같은 cluster 가 다른 ID 받아 wiki page 가 daily_update 마다 누적.
  현 구현은 cluster 내 _article_id sorted hash → 순서 무관 deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.core.dedupe import cluster_events, assign_article_ids


def _make_articles(seed_specs: list[tuple]) -> list[dict]:
    """spec: (date, source, title, primary_topic) → articles list."""
    arts = []
    for d, s, t, topic in seed_specs:
        arts.append({
            'date': d,
            'source': s,
            'title': t,
            'primary_topic': topic,
            'is_primary': True,
        })
    assign_article_ids(arts)
    return arts


def test_event_group_id_independent_of_input_order():
    """동일 article set 입력 순서 변경 → 동일 event_group_id 매핑."""
    specs = [
        ('2026-04-08', '뉴시스', "원·달러, 미·이란 '2주 휴전'에 24.3원 급락", '환율_FX'),
        ('2026-04-08', '연합뉴스', "원달러 환율 24원 폭락 휴전 합의", '환율_FX'),
        ('2026-04-08', '뉴스1', "코스피, 휴전 기대 5% 급등", '주식'),
        ('2026-04-09', '연합뉴스', "유가 급등 IEA 경고", '에너지_원자재'),
    ]

    a1 = _make_articles(specs)
    cluster_events(a1)
    map1 = {a['_article_id']: a['_event_group_id'] for a in a1}

    # input 순서 reverse
    a2 = _make_articles(list(reversed(specs)))
    cluster_events(a2)
    map2 = {a['_article_id']: a['_event_group_id'] for a in a2}

    assert map1 == map2, (
        f'순서 의존 발견 — 같은 article_id 가 다른 event_group_id 받음.\n'
        f'  forward : {map1}\n'
        f'  reversed: {map2}'
    )


def test_event_group_id_stable_across_runs():
    """같은 입력 2회 실행 → 동일 event_group_id."""
    specs = [
        ('2026-04-08', '뉴시스', "원·달러, 미·이란 '2주 휴전'에 24.3원 급락", '환율_FX'),
        ('2026-04-08', '연합뉴스', "원달러 환율 24원 폭락 휴전 합의", '환율_FX'),
    ]
    a1 = _make_articles(specs)
    cluster_events(a1)
    a2 = _make_articles(specs)
    cluster_events(a2)
    ids1 = sorted({a['_event_group_id'] for a in a1})
    ids2 = sorted({a['_event_group_id'] for a in a2})
    assert ids1 == ids2


def test_event_group_id_format():
    """ID 가 'event_{10자hex}' 형태."""
    import re
    specs = [('2026-04-08', '뉴시스', "테스트 헤드라인", '환율_FX')]
    a = _make_articles(specs)
    cluster_events(a)
    gid = a[0]['_event_group_id']
    assert re.fullmatch(r'event_[0-9a-f]{10}', gid), f'unexpected format: {gid!r}'


if __name__ == '__main__':
    test_event_group_id_independent_of_input_order()
    print('PASS test_event_group_id_independent_of_input_order')
    test_event_group_id_stable_across_runs()
    print('PASS test_event_group_id_stable_across_runs')
    test_event_group_id_format()
    print('PASS test_event_group_id_format')
    print('ALL PASS')
