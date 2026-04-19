# -*- coding: utf-8 -*-
"""taxonomy contract 테스트 (review packet v11).

세 가지 케이스:
  1. 정상 taxonomy 일치 — overlap > 0
  2. phrase 유입 방지 — normalize 후 topic_tags에 phrase 없음
  3. empty tags fallback — shift 보류 (description 기반 판정 금지)
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import date
from pathlib import Path


def _pass(name: str):
    print(f'  PASS — {name}')


def _fail(name: str, msg: str):
    print(f'  FAIL — {name}: {msg}')
    raise AssertionError(f'{name}: {msg}')


def test_case_1_exact_match():
    """정상 taxonomy 매칭: overlap > 0."""
    from market_research.wiki.canonical import normalize_regime_memory
    from market_research.wiki.taxonomy import TAXONOMY_SET

    regime = {
        'current': {
            'dominant_narrative': '지정학 + 환율_FX + 에너지_원자재',
            'topic_tags': ['지정학', '환율_FX', '에너지_원자재'],
            'since': '2026-04-17',
            'direction': 'bearish',
        },
        'history': [],
    }
    n = normalize_regime_memory(regime)
    tags = set(n['current']['topic_tags'])

    if tags != {'지정학', '환율_FX', '에너지_원자재'}:
        _fail('case1.tags_preserved', f'예상 {tags}')

    if n['current'].get('_unresolved_tags'):
        _fail('case1.no_unresolved', f'unresolved={n["current"]["_unresolved_tags"]}')

    delta_top = {'지정학', '환율_FX', '에너지_원자재', '금리_채권'}
    overlap = tags & delta_top
    if len(overlap) < 1:
        _fail('case1.overlap', f'overlap={overlap}')
    _pass('case1: 정상 taxonomy 매칭 (overlap = 3)')


def test_case_2_phrase_rejection():
    """phrase 유입 방지: '지정학 완화' → '지정학'으로 매핑, 매핑 실패 phrase는 unresolved."""
    from market_research.wiki.canonical import normalize_regime_memory
    from market_research.wiki.taxonomy import TAXONOMY_SET

    regime = {
        'current': {
            'dominant_narrative': '지정학 완화 + 구조적 인플레 + 단기 랠리와 장기 리스크의 불일치',
            'topic_tags': ['지정학 완화', '구조적 인플레', '단기 랠리와 장기 리스크의 불일치'],
            'since': '2026-04-01',
        },
        'history': [],
    }
    n = normalize_regime_memory(regime)
    tags = n['current']['topic_tags']

    # 모든 topic_tags는 taxonomy여야 함
    non_taxonomy = [t for t in tags if t not in TAXONOMY_SET]
    if non_taxonomy:
        _fail('case2.taxonomy_only', f'phrase 섞임: {non_taxonomy}')

    # alias로 매핑된 것은 기대됨
    if '지정학' not in tags:
        _fail('case2.alias_mapping', f'지정학 완화 → 지정학 매핑 실패. tags={tags}')
    if '물가_인플레이션' not in tags:
        _fail('case2.alias_mapping_inflation', f'구조적 인플레 → 물가_인플레이션 매핑 실패. tags={tags}')

    # 매핑 불가한 phrase는 unresolved
    unresolved = n['current'].get('_unresolved_tags', [])
    if not unresolved:
        _fail('case2.unresolved_recorded', '매핑 실패 phrase 미기록')

    # description 보존
    desc = n['current'].get('narrative_description', '')
    if '구조적 인플레' not in desc and '지정학 완화' not in desc:
        _fail('case2.description_preserved', f'description 원문 손실: {desc}')

    _pass(f'case2: phrase 유입 차단 (tags={tags}, unresolved={unresolved})')


def test_case_3_empty_tags_fallback():
    """empty tags 상태에서는 shift 후보로 올리지 않음."""
    from market_research.wiki.canonical import normalize_regime_memory

    regime = {
        'current': {
            'dominant_narrative': '',
            'topic_tags': [],
            'since': date.today().isoformat(),
        },
        'history': [],
    }
    n = normalize_regime_memory(regime)
    if n['current']['topic_tags']:
        _fail('case3.tags_stay_empty', f'tags={n["current"]["topic_tags"]}')

    # _step_regime_check 호출 — empty tags 경로 확인
    from market_research.pipeline.daily_update import _step_regime_check
    # regime_memory.json을 임시로 덮어써서 호출
    import market_research.pipeline.daily_update as du
    regime_file = du.REGIME_FILE
    backup = regime_file.read_bytes()
    try:
        regime_file.write_text(json.dumps(n, ensure_ascii=False), encoding='utf-8')
        delta = {'topic_counts': {'지정학': 5, '환율_FX': 3, '에너지_원자재': 2}, 'sentiment': 'negative'}
        result = _step_regime_check(delta)
        if result.get('shift_consecutive_days', 0) != 0:
            _fail('case3.no_shift_candidate',
                  f'빈 태그에서 shift 후보 생성됨: {result}')
        _pass('case3: empty tags → shift 보류')
    finally:
        regime_file.write_bytes(backup)
        # canonical page도 되돌리기
        from market_research.wiki.canonical import update_canonical_regime
        update_canonical_regime(regime_file)


def main():
    print('\n=== Taxonomy contract tests ===')
    results = []
    for fn in (test_case_1_exact_match, test_case_2_phrase_rejection, test_case_3_empty_tags_fallback):
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
