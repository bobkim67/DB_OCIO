# -*- coding: utf-8 -*-
"""09 선택 claim_type 쿼터 (2026-08-06 사용자 지시).

★ 배경: 09 는 자산군당 salience 상위 12건만 싣는데, `salience` 는 추출 프롬프트에
  **정의가 없다**(schema 에 `"salience": 0.0~1.0` 한 줄뿐, system prompt 는 언급도
  안 함). Haiku 가 루브릭 없이 매기니 눈에 띄는 **사건**이 상위를 차지하고
  **전망**이 밀렸다.

  2026-07 실측 top-12:
    해외주식 — 전체 outlook_view 359건(52%) 인데 top-12 에 **0건**
    국내주식 — 전체 outlook_view 308건(46%) 인데 top-12 에 **1건**
    대체     — event_to_macro 가 전체 24% 인데 top-12 의 **58%**

검증:
  1. 쿼터가 전망·리스크 최소 수를 보장
  2. quota 없으면 기존 `[:n]` 과 **완전 동일** (골든 불변)
  3. 쿼터 채울 claim 이 부족하면 일반 순위로 degrade (에러 없이)
  4. 출력은 원래 salience 순 유지
"""
from __future__ import annotations

import pytest

from market_research.analyze.research_aggregator import (
    BROKER_CLAIM_QUOTA, select_balanced,
)


def _c(i: int, ctype: str, sal: float) -> dict:
    return {'claim_id': f'c{i}', 'claim_type': ctype, 'salience': sal}


def _pool() -> list[dict]:
    """salience 내림차순. 상위는 전부 사건/매크로, 전망은 아래에 깔린다."""
    out = [_c(i, 'macro_to_asset', 0.95 - i * 0.01) for i in range(10)]
    out += [_c(100 + i, 'event_to_macro', 0.84 - i * 0.01) for i in range(5)]
    out += [_c(200 + i, 'outlook_view', 0.78 - i * 0.01) for i in range(20)]
    out += [_c(300 + i, 'risk', 0.60 - i * 0.01) for i in range(5)]
    return out


def _types(rows):
    from collections import Counter
    return Counter(r['claim_type'] for r in rows)


# ────────────────────────── 1. 쿼터 보장 ──────────────────────────

def test_quota_guarantees_outlook_and_risk():
    got = select_balanced(_pool(), 12, BROKER_CLAIM_QUOTA)
    t = _types(got)
    assert len(got) == 12
    assert t['outlook_view'] >= 4
    assert t['risk'] >= 2


def test_without_quota_top_slots_are_all_events():
    """쿼터 없으면 전망이 0건 — 이게 고치려던 상태."""
    t = _types(select_balanced(_pool(), 12))
    assert t['outlook_view'] == 0


# ────────────────────────── 2. 골든 불변 ──────────────────────────

@pytest.mark.parametrize('quota', [None, {}])
def test_no_quota_matches_legacy_slice(quota):
    pool = _pool()
    assert select_balanced(pool, 12, quota) == pool[:12]


def test_empty_and_small_inputs():
    assert select_balanced([], 12, BROKER_CLAIM_QUOTA) == []
    assert select_balanced(_pool(), 0, BROKER_CLAIM_QUOTA) == []
    small = _pool()[:3]
    assert select_balanced(small, 12, BROKER_CLAIM_QUOTA) == small


# ────────────────────────── 3. degrade ──────────────────────────

def test_degrades_when_quota_type_absent():
    """쿼터 대상 타입이 아예 없으면 일반 순위로 채운다 (에러 없이)."""
    pool = [_c(i, 'macro_to_asset', 0.9 - i * 0.01) for i in range(20)]
    got = select_balanced(pool, 12, BROKER_CLAIM_QUOTA)
    assert got == pool[:12]


def test_partial_quota_fill():
    """전망이 2건뿐이면 2건만 넣고 나머지는 일반 순위."""
    pool = [_c(i, 'macro_to_asset', 0.9 - i * 0.01) for i in range(20)]
    pool += [_c(90, 'outlook_view', 0.5), _c(91, 'outlook_view', 0.4)]
    got = select_balanced(pool, 12, {'outlook_view': 4})
    assert _types(got)['outlook_view'] == 2
    assert len(got) == 12


# ────────────────────────── 4. 순서 ──────────────────────────

def test_output_keeps_salience_order():
    got = select_balanced(_pool(), 12, BROKER_CLAIM_QUOTA)
    sals = [r['salience'] for r in got]
    assert sals == sorted(sals, reverse=True)


def test_no_duplicates():
    got = select_balanced(_pool(), 12, BROKER_CLAIM_QUOTA)
    assert len({r['claim_id'] for r in got}) == len(got)
