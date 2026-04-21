# -*- coding: utf-8 -*-
"""Regime shift 판정식 v12 테스트.

네 가지 케이스:
  (a) current 2 tags / today 5 tags / intersection 1 — 즉시 shift 안됨
  (b) intersection 0 + sentiment_flip — candidate 가능
  (c) current tags 1개 — sentiment_flip 없이 shift 금지
  (d) current tags 0개 — warning + hold
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import date
from pathlib import Path


def _with_regime(regime_dict, delta_dict):
    """임시로 regime_memory.json을 대체 후 _step_regime_check 호출. 원복."""
    import market_research.pipeline.daily_update as du
    from market_research.wiki.canonical import update_canonical_regime
    regime_file = du.REGIME_FILE
    backup = regime_file.read_bytes()
    try:
        regime_file.write_text(json.dumps(regime_dict, ensure_ascii=False), encoding='utf-8')
        return du._step_regime_check(delta_dict)
    finally:
        regime_file.write_bytes(backup)
        update_canonical_regime(regime_file)


def _last_quality_record():
    p = Path(__file__).resolve().parent.parent / 'data' / 'report_output' / '_regime_quality.jsonl'
    if not p.exists():
        return {}
    lines = p.read_text(encoding='utf-8').strip().split('\n')
    return json.loads(lines[-1]) if lines else {}


def _pass(name, detail=''):
    print(f'  PASS — {name}: {detail}')


def _fail(name, msg):
    print(f'  FAIL — {name}: {msg}')
    raise AssertionError(f'{name}: {msg}')


# ══════════════════════════════════════════
# 케이스 a: 2 tags / today 5 / intersection 1
# ══════════════════════════════════════════

def test_case_a_intersection_one_of_five():
    regime = {
        'current': {
            'dominant_narrative': '지정학 + 물가_인플레이션',
            'topic_tags': ['지정학', '물가_인플레이션'],
            'since': '2026-04-01',
            'direction': 'bearish',
        },
        'history': [],
    }
    # 5개 중 지정학만 교집합, 나머지 4개는 모두 다른 토픽
    delta = {
        'topic_counts': {'환율_FX': 10, '에너지_원자재': 8, '통화정책': 6, '지정학': 4, '경기_소비': 3},
        'sentiment': 'negative',   # current=bearish와 동일 → flip=False
    }
    _with_regime(regime, delta)
    q = _last_quality_record()

    # 확인:
    # - coverage_current = 1/2 = 0.5 → low_current = False (< 0.5 이므로 경계)
    #   실제로 0.5 기준이라면 low_current = (0.5 < 0.5) = False
    # - coverage_today = core(환율_FX, 에너지_원자재, 통화정책) 교집합 0 = 0/3 → low_today = True
    # - sentiment_flip = False
    # → rules = [low_today], score = 1 → shift_candidate = False
    if q.get('shift_candidate'):
        _fail('case_a', f'1/5 overlap만으로 shift candidate가 떴음: rules={q.get("candidate_rules_triggered")}')
    _pass('case_a: 1/5 overlap → 즉시 shift 안됨',
          f'cov_curr={q.get("coverage_current")}, cov_today={q.get("coverage_today")}, '
          f'rules={q.get("candidate_rules_triggered")}')


# ══════════════════════════════════════════
# 케이스 b: intersection 0 + sentiment_flip
# ══════════════════════════════════════════

def test_case_b_flip_triggers_candidate():
    regime = {
        'current': {
            'dominant_narrative': '지정학 + 물가_인플레이션',
            'topic_tags': ['지정학', '물가_인플레이션'],
            'since': '2026-04-01',
            'direction': 'bullish',   # ← 기존 bullish
        },
        'history': [],
    }
    delta = {
        'topic_counts': {'환율_FX': 10, '에너지_원자재': 8, '통화정책': 6, '크립토': 4, '부동산': 3},
        'sentiment': 'negative',   # ← flip
    }
    _with_regime(regime, delta)
    q = _last_quality_record()

    # coverage_current = 0, coverage_today = 0, sentiment_flip = True
    # rules = all 3, score = 3 → candidate
    if not q.get('shift_candidate'):
        _fail('case_b', f'flip+no overlap인데 candidate 아님: q={q}')
    if not q.get('sentiment_flip'):
        _fail('case_b.flip_flag', 'sentiment_flip=False')
    _pass('case_b: intersection 0 + sentiment_flip → candidate',
          f'rules={q.get("candidate_rules_triggered")}, score={q.get("candidate_score")}')


# ══════════════════════════════════════════
# 케이스 c: single tag — coverage_current만으로 shift 금지
# ══════════════════════════════════════════

def test_case_c_single_tag_needs_flip():
    # 시나리오 1: 단일 태그 + flip 없음 → shift 금지
    regime1 = {
        'current': {
            'dominant_narrative': '지정학',
            'topic_tags': ['지정학'],
            'since': '2026-04-01',
            'direction': 'neutral',
        },
        'history': [],
    }
    delta_no_flip = {
        'topic_counts': {'환율_FX': 10, '에너지_원자재': 8, '통화정책': 6, '물가_인플레이션': 4, '경기_소비': 3},
        'sentiment': 'mixed',   # neutral과 호환, flip=False
    }
    _with_regime(regime1, delta_no_flip)
    q1 = _last_quality_record()
    if q1.get('shift_candidate'):
        _fail('case_c.1', f'단일 태그 + no flip인데 candidate: q={q1}')

    # 시나리오 2: 단일 태그 + flip 있음 → candidate 가능
    regime2 = {
        'current': {
            'dominant_narrative': '지정학',
            'topic_tags': ['지정학'],
            'since': '2026-04-01',
            'direction': 'bearish',
        },
        'history': [],
    }
    delta_flip = {
        'topic_counts': {'환율_FX': 10, '테크_AI_반도체': 8, '경기_소비': 6, '크립토': 4, '부동산': 3},
        'sentiment': 'positive',
    }
    _with_regime(regime2, delta_flip)
    q2 = _last_quality_record()
    if not q2.get('shift_candidate'):
        _fail('case_c.2', f'단일 태그 + flip인데 candidate 아님: q={q2}')

    _pass('case_c: single tag — flip 없으면 hold, flip 있으면 candidate',
          f'no_flip={q1.get("shift_candidate")}, with_flip={q2.get("shift_candidate")}')


# ══════════════════════════════════════════
# 케이스 d: empty tags — hold + warning
# ══════════════════════════════════════════

def test_case_d_empty_tags_hold():
    regime = {
        'current': {
            'dominant_narrative': '',
            'topic_tags': [],
            'since': date.today().isoformat(),
            'direction': 'neutral',
        },
        'history': [],
    }
    delta = {
        'topic_counts': {'지정학': 5, '환율_FX': 3, '에너지_원자재': 2},
        'sentiment': 'negative',
    }
    _with_regime(regime, delta)
    q = _last_quality_record()

    if q.get('shift_candidate'):
        _fail('case_d', f'empty tags인데 candidate: q={q}')
    reason = q.get('shift_reason', '')
    if '비어있음' not in reason and 'hold' not in reason:
        _fail('case_d.warning', f'warning/hold reason 없음: {reason}')
    _pass('case_d: empty tags → hold + warning', f'reason="{reason}"')


def main():
    print('\n=== Regime decision v12 tests ===')
    results = []
    for fn in (test_case_a_intersection_one_of_five, test_case_b_flip_triggers_candidate,
               test_case_c_single_tag_needs_flip, test_case_d_empty_tags_hold):
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
