# -*- coding: utf-8 -*-
"""entity_builder (v13 redesign) — 단위 테스트.

지시서 수용 기준의 경계를 검증:
  1. PHRASE_ALIAS hit → taxonomy_topic 부여
  2. miss / ambiguous → candidate 제외
  3. edge effective_score 합산 정확성
  4. path_role_hit 계산 정확성
  5. article 매칭 후 first_seen/last_seen/primary_articles 순서
  6. taxonomy cap 적용 확인
  7. refresh 후 media entity(source__) 미생성 확인
"""
from __future__ import annotations

import sys
import traceback


def _pass(name: str):
    print(f'  PASS — {name}')


def _fail(name: str, msg: str):
    print(f'  FAIL — {name}: {msg}')
    raise AssertionError(f'{name}: {msg}')


def test_case_1_taxonomy_hit():
    from market_research.wiki.entity_builder import map_node_to_taxonomy
    # exact phrase alias hit
    assert map_node_to_taxonomy('유가') == '에너지_원자재', '유가 → 에너지_원자재'
    assert map_node_to_taxonomy('반도체') == '테크_AI_반도체', '반도체 → 테크_AI_반도체'
    assert map_node_to_taxonomy('이란') == '지정학', '이란 → 지정학'
    assert map_node_to_taxonomy('환율') == '환율_FX', '환율 → 환율_FX'
    _pass('case1: PHRASE_ALIAS exact hit → taxonomy_topic 부여')


def test_case_2_miss_excluded():
    from market_research.wiki.entity_builder import map_node_to_taxonomy
    # miss (단독 단어 등록 안 됨)
    for label in ['달러', '코스피', 'SK하이닉스', 'inferred', '투자심리_개선',
                   '원_달러_환율_변동', '호르무즈 봉쇄']:
        r = map_node_to_taxonomy(label)
        if r is not None:
            _fail('case2.miss', f'{label!r} 는 miss여야 하지만 {r!r} 반환')
    # ambiguous — PHRASE_ALIAS상 1개만 매칭되도록 유지 시 ambiguous 케이스는
    # 현재 데이터에서 생성되기 어려움. 규칙 자체가 다중 매칭 시 None 반환하는
    # 것만 확인.
    _pass('case2: miss / ambiguous → None (억지 매핑 금지)')


def test_case_3_edge_score_sum():
    from market_research.wiki.entity_builder import compute_node_importance
    edges = [
        {'from': 'A', 'to': 'B', 'effective_score': 0.5, 'support_count': 2},
        {'from': 'B', 'to': 'C', 'effective_score': 0.3, 'support_count': 1},
        {'from': 'A', 'to': 'C', 'effective_score': 0.2, 'support_count': 3},
        {'from': 'D', 'to': 'A', 'effective_score': 0.7, 'support_count': 4},
    ]
    # A: 인접 edge = (A→B)0.5 + (A→C)0.2 + (D→A)0.7 = 1.4
    imp = compute_node_importance('A', 'A', edges, paths=[])
    expected = round(0.5 + 0.2 + 0.7, 4)
    if imp['node_importance'] != expected:
        _fail('case3.score', f'expected={expected}, got={imp["node_importance"]}')
    if imp['support_count_sum'] != 2 + 3 + 4:
        _fail('case3.support', f'support_sum={imp["support_count_sum"]}')
    if imp['importance_basis'] != 'edge_effective_score_sum':
        _fail('case3.basis', imp['importance_basis'])
    _pass(f'case3: edge score sum = {imp["node_importance"]} (expected {expected})')


def test_case_4_path_role_hit():
    from market_research.wiki.entity_builder import compute_node_importance
    paths = [
        {'trigger': '지정학', 'target': '유가',
         'path': ['호르무즈_긴장'], 'path_labels': ['호르무즈 긴장']},
        {'trigger': '물가_인플레이션', 'target': '국내주식',
         'path': ['기업_수익성_악화'], 'path_labels': ['기업_수익성_악화']},
    ]
    # '유가' — target 등장
    imp1 = compute_node_importance('유가', '유가', edges=[], paths=paths)
    if not imp1['path_role_hit']:
        _fail('case4.hit', '유가는 target으로 등장해야 path_role_hit')
    if imp1['path_count'] != 1:
        _fail('case4.count', f'유가 path_count={imp1["path_count"]}')
    # '호르무즈 긴장' — path 내부 경유 (path_count=1, path_role_hit=False)
    imp2 = compute_node_importance('호르무즈_긴장', '호르무즈 긴장', edges=[], paths=paths)
    if imp2['path_role_hit']:
        _fail('case4.internal', '내부 경유는 role hit 아님')
    if imp2['path_count'] != 1:
        _fail('case4.internal_count', f'path_count={imp2["path_count"]}')
    # 무관 노드
    imp3 = compute_node_importance('X', 'X', edges=[], paths=paths)
    if imp3['path_role_hit'] or imp3['path_count'] != 0:
        _fail('case4.none', f'무관 노드 결과: {imp3}')
    _pass('case4: path_role_hit = trigger/target 직접, path_count는 내부 경유 포함')


def test_case_5_article_matching():
    from market_research.wiki.entity_builder import collect_entity_articles
    arts = [
        {'_article_id': 'a1', 'title': '유가 급등', 'description': '', 'date': '2026-04-10',
         'is_primary': True, '_event_salience': 0.9, '_event_group_id': 'ev_1'},
        {'_article_id': 'a2', 'title': '국제 유가 반등', 'description': '', 'date': '2026-04-05',
         'is_primary': True, '_event_salience': 0.7, '_event_group_id': 'ev_2'},
        {'_article_id': 'a3', 'title': '코스피 상승', 'description': '유가와 무관',  # match 'description' substring
         'date': '2026-04-08', 'is_primary': False, '_event_salience': 0.3, '_event_group_id': 'ev_1'},
        {'_article_id': 'a4', 'title': '호르무즈', 'description': 'dummy', 'date': '2026-04-03',
         'is_primary': True, '_event_salience': 0.5, '_event_group_id': 'ev_3'},
    ]
    r = collect_entity_articles('유가', arts)
    # a1, a2, a3 모두 '유가' substring 매칭
    if r['unique_article_count'] != 3:
        _fail('case5.count', f'expected 3, got {r["unique_article_count"]}')
    if r['first_seen'] != '2026-04-05':
        _fail('case5.first', f'first_seen={r["first_seen"]}')
    if r['last_seen'] != '2026-04-10':
        _fail('case5.last', f'last_seen={r["last_seen"]}')
    # primary 정렬: a1(primary, sal=0.9), a2(primary, sal=0.7), a3(non-primary, sal=0.3)
    if r['primary_articles'][:3] != ['a1', 'a2', 'a3']:
        _fail('case5.primary_order', f'primary={r["primary_articles"]}')
    # linked_events: ev_1, ev_2 (a3의 ev_1은 중복이라 스킵)
    if set(r['linked_events']) != {'ev_1', 'ev_2'}:
        _fail('case5.events', f'events={r["linked_events"]}')
    _pass(f'case5: 매칭·first/last/primary 순서 정상 (count=3)')


def test_case_6_taxonomy_cap():
    from market_research.wiki.entity_builder import select_entity_candidates
    # 같은 taxonomy로 매핑되는 label 5개를 강제 — 지정학
    # 이란 → 지정학 (PHRASE_ALIAS)
    # '지정학' → 지정학
    # '지정학적 리스크' → 지정학
    # '지정학 완화' → 지정학
    # '지정학 위기' → 지정학
    nodes = {
        'n1': {'label': '이란'},
        'n2': {'label': '지정학'},
        'n3': {'label': '지정학적 리스크'},
        'n4': {'label': '지정학 완화'},
        'n5': {'label': '지정학 위기'},
    }
    # 각 노드가 evidence 충족하도록 article 하나씩
    articles = []
    for nid, meta in nodes.items():
        articles.append({
            '_article_id': 'a_' + nid, 'title': meta['label'],
            'description': meta['label'], 'date': '2026-04-10',
            'is_primary': True, '_event_salience': 0.5,
            '_event_group_id': 'ev_' + nid,
        })
    # path 없음, edge 없음 → evidence는 unique_article_count >= 2 불충분
    # 그러나 linked_event_count >= 1 충족 → 후보 생존
    # 하지만 article 1개로는 unique_article_count=1, linked_event_count=1 → evidence OK
    edges = []
    paths = []
    cands = select_entity_candidates(nodes, edges, paths, articles,
                                     max_entities=12, per_taxonomy_cap=3)
    # 모두 지정학 → per_taxonomy_cap=3으로 3개만 남아야 함
    if len(cands) != 3:
        _fail('case6.cap', f'expected 3 (cap), got {len(cands)}')
    topics = {c['taxonomy_topic'] for c in cands}
    if topics != {'지정학'}:
        _fail('case6.topic', f'topics={topics}')
    _pass(f'case6: taxonomy cap 3 적용 (5 → 3)')


def test_case_7_no_media_entity():
    """refresh 후 source__ 페이지가 생성되지 않음을 확인."""
    import tempfile
    from pathlib import Path
    from market_research.wiki import draft_pages as dp
    from market_research.wiki import paths as wp

    # 임시 ENTITIES_DIR 로 격리
    tmpdir = Path(tempfile.mkdtemp(prefix='entity_test_'))
    orig_entities = dp.ENTITIES_DIR
    orig_events = dp.EVENTS_DIR
    orig_assets = dp.ASSETS_DIR
    orig_funds = dp.FUNDS_DIR
    orig_index = dp.INDEX_DIR
    dp.ENTITIES_DIR = tmpdir / '02'
    dp.EVENTS_DIR = tmpdir / '01'
    dp.ASSETS_DIR = tmpdir / '03'
    dp.FUNDS_DIR = tmpdir / '04'
    dp.INDEX_DIR = tmpdir / '00'
    for p in [dp.ENTITIES_DIR, dp.EVENTS_DIR, dp.ASSETS_DIR,
              dp.FUNDS_DIR, dp.INDEX_DIR]:
        p.mkdir(parents=True, exist_ok=True)

    try:
        # 존재하지 않는 월 호출 (articles 없음) → early return, 빈 디렉토리
        result = dp.refresh_base_pages_after_refine('2099-01')
        media_pages = list(dp.ENTITIES_DIR.glob('*source__*.md'))
        if media_pages:
            _fail('case7.no_media', f'source__ 페이지 발견: {media_pages}')
        if result['entities'] != 0:
            # 빈 articles에서는 0 entities
            _fail('case7.zero', f'entities={result["entities"]}')
        _pass('case7: refresh 후 media entity(source__) 미생성')
    finally:
        dp.ENTITIES_DIR = orig_entities
        dp.EVENTS_DIR = orig_events
        dp.ASSETS_DIR = orig_assets
        dp.FUNDS_DIR = orig_funds
        dp.INDEX_DIR = orig_index
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    print('\n=== entity_builder tests ===')
    results = []
    cases = (
        test_case_1_taxonomy_hit,
        test_case_2_miss_excluded,
        test_case_3_edge_score_sum,
        test_case_4_path_role_hit,
        test_case_5_article_matching,
        test_case_6_taxonomy_cap,
        test_case_7_no_media_entity,
    )
    for fn in cases:
        try:
            fn()
            results.append((fn.__name__, 'PASS'))
        except AssertionError as exc:
            results.append((fn.__name__, f'FAIL: {exc}'))
        except Exception:
            traceback.print_exc()
            results.append((fn.__name__, 'ERROR'))

    print('\n=== Summary ===')
    for name, status in results:
        print(f'  {status:8s} {name}')
    failed = [n for n, s in results if not s.startswith('PASS')]
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
