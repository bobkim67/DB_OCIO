# -*- coding: utf-8 -*-
"""Tests for v13.1 entity page redesign (graph-structure driven).

Schema changes vs legacy (v12.1) demo:
  - node_severity / has_draft_evidence / draft_sources  → removed
  - taxonomy_topic / node_importance / importance_basis
    support_count_sum / path_count / path_role_hit
    unique_article_count / first_seen / last_seen / primary_articles → added
  - Body sections:  Confirmed facts + Graph provenance  (no Draft evidence,
    no adjacency list, no transmission path detail — those live in 07_Graph_Evidence/)

Cases:
  1. graphnode candidate — new sections present, new frontmatter fields present
  2. Legacy fields absent (no severity, no has_draft_evidence)
  3. Empty candidate (no articles) renders safely
  4. Stable page id — rerun overwrites
  5. Base page body has NO adjacency/path detail (negative test)
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


def _sample_candidate(**overrides) -> dict:
    base = {
        'entity_id': 'graphnode__유가',
        'graph_node_id': '유가',
        'label': '유가',
        'taxonomy_topic': '에너지_원자재',
        'node_importance': 4.0884,
        'importance_basis': 'edge_effective_score_sum',
        'edge_score_sum': 4.0884,
        'support_count_sum': 16,
        'path_count': 1,
        'path_role_hit': True,
        'unique_article_count': 42,
        'first_seen': '2026-04-03',
        'last_seen': '2026-04-20',
        'primary_articles': ['a1', 'a2', 'a3'],
        'recent_titles': ['호르무즈 긴장에 유가 반등', '국제유가 7% 급등'],
        'linked_events': ['event_2213', 'event_2850'],
        'linked_event_count': 2,
        'unique_article_ids': ['a1', 'a2', 'a3'],
    }
    base.update(overrides)
    return base


def test_case_1_new_sections_present():
    original, tmp = _with_tmp_entities_dir()
    try:
        out = draft_pages.write_entity_page(_sample_candidate(), '2026-04')
        txt = Path(out).read_text(encoding='utf-8')
        for needle in [
            '## Confirmed facts',
            '## Graph provenance',
            'taxonomy_topic: 에너지_원자재',
            'node_importance: 4.0884',
            'support_count_sum: 16',
            'path_count: 1',
            'path_role_hit: true',
            'primary_articles: [a1, a2, a3]',
            'Detailed adjacency and transmission paths are available in',
        ]:
            if needle not in txt:
                _fail('case1.needle', f'missing `{needle}`')
        _pass('case1: new sections + frontmatter fields present')
    finally:
        _restore(original)


def test_case_2_legacy_fields_absent():
    original, tmp = _with_tmp_entities_dir()
    try:
        out = draft_pages.write_entity_page(_sample_candidate(), '2026-04')
        txt = Path(out).read_text(encoding='utf-8')
        for banned in [
            'node_severity:',
            'has_draft_evidence:',
            'draft_sources:',
            'Draft evidence',            # legacy section header
            'Graph adjacency (top 5)',   # legacy subsection
            'Transmission paths involving this node',  # legacy subsection
        ]:
            if banned in txt:
                _fail('case2.legacy_field', f'legacy field/section present: `{banned}`')
        _pass('case2: legacy severity/draft fields removed')
    finally:
        _restore(original)


def test_case_3_empty_articles_safe():
    original, tmp = _with_tmp_entities_dir()
    try:
        c = _sample_candidate(
            recent_titles=[], primary_articles=[], linked_events=[],
            unique_article_count=0, first_seen='', last_seen='',
            linked_event_count=0,
        )
        out = draft_pages.write_entity_page(c, '2026-04')
        txt = Path(out).read_text(encoding='utf-8')
        if '_No articles matched this entity this period._' not in txt:
            _fail('case3.fallback', 'empty recent_titles fallback missing')
        if 'Mention summary: 0 articles' not in txt:
            _fail('case3.mention_zero', 'expected zero-mention summary')
        if 'Linked events: —' not in txt:
            _fail('case3.events_dash', 'em-dash fallback for linked events missing')
        _pass('case3: empty candidate renders safely')
    finally:
        _restore(original)


def test_case_4_stable_page_id():
    original, tmp = _with_tmp_entities_dir()
    try:
        p1 = draft_pages.write_entity_page(
            _sample_candidate(entity_id='graphnode__환율', label='환율',
                               taxonomy_topic='환율_FX', graph_node_id='환율',
                               recent_titles=['환율 1495원']),
            '2026-04',
        )
        p2 = draft_pages.write_entity_page(
            _sample_candidate(entity_id='graphnode__환율', label='환율',
                               taxonomy_topic='환율_FX', graph_node_id='환율',
                               recent_titles=['환율 1500원', '새로운 언급']),
            '2026-04',
        )
        if Path(p1) != Path(p2):
            _fail('case4.stable_path', f'{p1} != {p2}')
        txt = Path(p2).read_text(encoding='utf-8')
        if '1500원' not in txt:
            _fail('case4.content_overwritten', 'new content missing')
        if '1495원' in txt:
            _fail('case4.old_content_lingered', 'old content persisted')
        _pass('case4: stable page id — rerun overwrites')
    finally:
        _restore(original)


def test_case_5_no_path_detail_in_body():
    """path_role_hit=True 라도 base page 본문엔 path 상세 없음 (07_Graph_Evidence/에만)."""
    original, tmp = _with_tmp_entities_dir()
    try:
        out = draft_pages.write_entity_page(
            _sample_candidate(path_role_hit=True, path_count=3),
            '2026-04',
        )
        txt = Path(out).read_text(encoding='utf-8')
        # frontmatter 플래그 True
        if 'path_role_hit: true' not in txt:
            _fail('case5.flag_true', 'path_role_hit=true missing in frontmatter')
        if 'path_count: 3' not in txt:
            _fail('case5.count', 'path_count=3 missing')
        # 본문엔 path 상세 노출 금지
        for banned in ['trigger `', ' → target `', 'conf=', 'path_labels']:
            if banned in txt:
                _fail('case5.body_no_path_detail', f'banned token in body: `{banned}`')
        # 링크만 허용
        if '07_Graph_Evidence/' not in txt:
            _fail('case5.link_missing', 'link to 07_Graph_Evidence missing')
        _pass('case5: path_role_hit in frontmatter, no path detail in body')
    finally:
        _restore(original)


def main():
    print('\n=== entity demo render tests (v13.1) ===')
    cases = [
        test_case_1_new_sections_present,
        test_case_2_legacy_fields_absent,
        test_case_3_empty_articles_safe,
        test_case_4_stable_page_id,
        test_case_5_no_path_detail_in_body,
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
