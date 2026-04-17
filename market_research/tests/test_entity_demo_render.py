# -*- coding: utf-8 -*-
"""Tests for v13 entity page redesign.

Cases:
  1. graphnode__유가 page has both "Confirmed facts" and "Draft evidence"
     headers, adjacency list (non-empty), transmission path list,
     and the draft-badge source marker.
  2. Media (source__) page still renders Confirmed + Draft headers but the
     draft section gracefully reports "Not applicable".
  3. Entity without graph_node_id + without adjacency does not crash;
     has_draft_evidence = false in frontmatter.
  4. Page stable id — rerunning write_entity_page with the same id
     overwrites the same file path, not a new one.
  5. Empty sections render safely (empty mentioned_in, no events,
     no graph node).
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

import market_research.wiki.draft_pages as draft_pages


def _pass(name: str):
    print(f'  PASS — {name}')


def _fail(name: str, msg: str):
    print(f'  FAIL — {name}: {msg}')
    raise AssertionError(f'{name}: {msg}')


def _with_tmp_entities_dir():
    tmp = Path(tempfile.mkdtemp(prefix='entity_render_test_'))
    original = draft_pages.ENTITIES_DIR
    draft_pages.ENTITIES_DIR = tmp
    return original, tmp


def _restore(original):
    draft_pages.ENTITIES_DIR = original


def test_case_1_graphnode_has_both_sections():
    original, tmp = _with_tmp_entities_dir()
    try:
        out = draft_pages.write_entity_page(
            entity_id='graphnode__유가',
            label='유가',
            topic='news',
            mentioned_in=[
                '[경제] 원유가 충격과 인플레, 그리고 금리',
                '국제유가 하락 전환',
            ],
            month_str='2026-04',
            graph_node_id='유가',
            canonical_entity_label='유가',
            linked_events=['event_12', 'event_29'],
            adjacent_nodes=[
                {'neighbor': '중동_긴장', 'direction': 'in',
                 'relation': 'causes', 'weight': 0.82},
                {'neighbor': '국제유가', 'direction': 'out',
                 'relation': 'triggers', 'weight': 0.66},
            ],
            paths_involving=[
                {'trigger': '유가_급등', 'target': '유가',
                 'path': ['유가_급등_압력', '국제유가'],
                 'path_labels': ['유가_급등_압력', '국제유가'],
                 'confidence': 0.663},
            ],
            graph_node_meta={'severity': 'neutral'},
        )
        txt = Path(out).read_text(encoding='utf-8')
        for needle in [
            '## Confirmed facts  _[source: `pipeline_refine`]_',
            '## Draft evidence  _[source: `07_Graph_Evidence` · draft]_',
            '### Graph adjacency (top 5)',
            '### Transmission paths involving this node',
            'has_draft_evidence: true',
            'draft_sources: [graph_evidence]',
            '국제유가',
            '유가_급등_압력',
        ]:
            if needle not in txt:
                _fail('case1.needle', f'missing `{needle}`')
        _pass('case1: graphnode page has both confirmed + draft sections')
    finally:
        _restore(original)


def test_case_2_media_entity_draft_fallback():
    original, tmp = _with_tmp_entities_dir()
    try:
        out = draft_pages.write_entity_page(
            entity_id='source__연합인포맥스',
            label='연합인포맥스',
            topic='매체',
            mentioned_in=['중동 리스크 장기화 우려',
                          'NDF 1495원', '스페이스X 한국 상륙'],
            month_str='2026-04',
            graph_node_id=None,
            canonical_entity_label=None,
            linked_events=['event_1944', 'event_1997'],
            adjacent_nodes=None,
            paths_involving=None,
            graph_node_meta=None,
        )
        txt = Path(out).read_text(encoding='utf-8')
        # header 섹션은 여전히 존재
        if '## Confirmed facts' not in txt:
            _fail('case2.confirmed_header', 'confirmed section missing')
        if '## Draft evidence' not in txt:
            _fail('case2.draft_header', 'draft section missing')
        # draft 내용은 N/A
        if 'Not applicable — media entity' not in txt:
            _fail('case2.media_notice',
                  'media N/A notice missing in adjacency block')
        if 'Not applicable for media entities' not in txt:
            _fail('case2.paths_notice',
                  'media N/A notice missing in paths block')
        if 'has_draft_evidence: false' not in txt:
            _fail('case2.frontmatter_draft_flag',
                  'has_draft_evidence should be false for media entity')
        if 'draft_sources:' in txt:
            _fail('case2.no_draft_sources_when_false',
                  'draft_sources should be omitted when has_draft_evidence=false')
        _pass('case2: media entity → Confirmed + Draft(N/A) rendered')
    finally:
        _restore(original)


def test_case_3_entity_without_graph_no_crash():
    original, tmp = _with_tmp_entities_dir()
    try:
        out = draft_pages.write_entity_page(
            entity_id='source__뉴스1',
            label='뉴스1',
            topic='매체',
            mentioned_in=[],
            month_str='2026-04',
            linked_events=[],
        )
        txt = Path(out).read_text(encoding='utf-8')
        if 'has_draft_evidence: false' not in txt:
            _fail('case3.flag_false', '')
        if '_No articles matched this entity this period._' not in txt:
            _fail('case3.empty_articles_fallback', '')
        if 'Not applicable' not in txt:
            _fail('case3.draft_na', '')
        _pass('case3: empty entity renders safely (no crash)')
    finally:
        _restore(original)


def test_case_4_stable_page_id_across_reruns():
    original, tmp = _with_tmp_entities_dir()
    try:
        p1 = draft_pages.write_entity_page(
            entity_id='graphnode__환율',
            label='환율',
            topic='news',
            mentioned_in=['환율 1495원'],
            month_str='2026-04',
            graph_node_id='환율',
            canonical_entity_label='환율',
            linked_events=['event_9'],
            adjacent_nodes=[{'neighbor': '달러', 'direction': 'in',
                             'relation': 'affects', 'weight': 0.7}],
            paths_involving=[],
        )
        # mutate content, rerun with same entity_id
        p2 = draft_pages.write_entity_page(
            entity_id='graphnode__환율',
            label='환율',
            topic='news',
            mentioned_in=['환율 1500원', '새로운 언급'],
            month_str='2026-04',
            graph_node_id='환율',
            canonical_entity_label='환율',
            linked_events=['event_9', 'event_10'],
            adjacent_nodes=[{'neighbor': '달러', 'direction': 'in',
                             'relation': 'affects', 'weight': 0.75}],
            paths_involving=[],
        )
        if Path(p1) != Path(p2):
            _fail('case4.stable_path',
                  f'p1={p1} != p2={p2}')
        txt = Path(p2).read_text(encoding='utf-8')
        if '1500원' not in txt:
            _fail('case4.content_overwritten', 'new content missing')
        if '1495원' in txt:
            _fail('case4.old_content_lingered',
                  'old content still present after rewrite')
        _pass('case4: stable page id — rerun overwrites same file')
    finally:
        _restore(original)


def test_case_5_no_graph_adj_but_has_path_flag_true():
    """If only paths_involving (no adjacency), has_draft_evidence=true."""
    original, tmp = _with_tmp_entities_dir()
    try:
        out = draft_pages.write_entity_page(
            entity_id='graphnode__테스트',
            label='테스트',
            topic='news',
            mentioned_in=['테스트 기사'],
            month_str='2026-04',
            graph_node_id='테스트',
            canonical_entity_label='테스트',
            linked_events=[],
            adjacent_nodes=None,
            paths_involving=[
                {'trigger': '테스트', 'target': '결과',
                 'path_labels': ['테스트', '중간', '결과'],
                 'confidence': 0.5},
            ],
        )
        txt = Path(out).read_text(encoding='utf-8')
        if 'has_draft_evidence: true' not in txt:
            _fail('case5.flag_true',
                  'has_draft_evidence should be true when paths present')
        if '_No adjacent edges recorded this period._' not in txt:
            _fail('case5.adj_empty_notice',
                  'empty adjacency notice missing')
        if '중간' not in txt:
            _fail('case5.path_rendered',
                  'path content missing')
        _pass('case5: paths-only entity → draft flag true, adjacency empty notice')
    finally:
        _restore(original)


def main():
    print('\n=== entity demo render tests ===')
    cases = [
        test_case_1_graphnode_has_both_sections,
        test_case_2_media_entity_draft_fallback,
        test_case_3_entity_without_graph_no_crash,
        test_case_4_stable_page_id_across_reruns,
        test_case_5_no_graph_adj_but_has_path_flag_true,
    ]
    results = []
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
