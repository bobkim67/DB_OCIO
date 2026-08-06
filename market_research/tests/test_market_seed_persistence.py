# -*- coding: utf-8 -*-
"""시드 저장/승인 + final 구조화 키 보존 (2026-08-05).

검증 대상:
  1. report_store.approve_and_save_final — asset_outlook / asset_movement_* /
     disagreements 를 **if-present** 보존. 값이 없으면 키를 만들지 않아
     **기존 산출물 형태가 그대로**여야 한다.
     ★ 배경: 종전 고정 12키 승인이라 debate 가 만든 구조화 산출물이 승인
       순간 버려졌다 (2026-07 실측: draft amc 5개 → final 0개).
  2. market_seed 저장/승인 라이프사이클 — load_approved_seed 는 승인본만.

LLM 호출 0. report_store OUTPUT_DIR 은 tmp 격리.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    from market_research.report import report_store
    root = tmp_path / 'report_output'
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, 'OUTPUT_DIR', root)
    monkeypatch.setattr(
        report_store, 'EVIDENCE_TRACKER', root / '_evidence_quality.jsonl')
    return root


# ────────────────────────── 1. final 키 보존 ──────────────────────────

def test_final_preserves_structured_keys(tmp_report_root):
    from market_research.report.report_store import (
        approve_and_save_final, load_final, save_draft,
    )
    save_draft('2026-08', '_market', {
        'draft_comment': '본문',
        'asset_outlook': {'국내주식': '전망 문장.'},
        'asset_outlook_period': '9월',
        'asset_movement_commentary': [{'asset_class': '국내주식'}],
        'asset_movement_anchors': {'국내주식': 'x'},
        'disagreements': [{'topic': '금리', 'bear': '상승'}],
    })
    approve_and_save_final('2026-08', '_market')
    final = load_final('2026-08', '_market')

    assert final['asset_outlook'] == {'국내주식': '전망 문장.'}
    assert final['asset_outlook_period'] == '9월'
    assert final['asset_movement_commentary'] == [{'asset_class': '국내주식'}]
    assert final['asset_movement_anchors'] == {'국내주식': 'x'}
    assert final['disagreements'] == [{'topic': '금리', 'bear': '상승'}]
    assert final['final_comment'] == '본문'


def test_final_omits_absent_keys(tmp_report_root):
    """★ 기존 산출물 형태 불변 — 값이 없으면 키 자체를 만들지 않는다."""
    from market_research.report.report_store import (
        approve_and_save_final, load_final, save_draft,
    )
    save_draft('2026-08', '_market', {'draft_comment': '본문'})
    approve_and_save_final('2026-08', '_market')
    final = load_final('2026-08', '_market')

    for k in ('asset_outlook', 'asset_outlook_period',
              'asset_movement_commentary', 'asset_movement_anchors',
              'disagreements'):
        assert k not in final, f'{k} 가 빈 값인데 final 에 기록됐다'


def test_empty_dict_does_not_create_key(tmp_report_root):
    """debate 가 전망 생성에 실패해 {} 를 넣어도 final 을 오염시키지 않는다."""
    from market_research.report.report_store import (
        approve_and_save_final, load_final, save_draft,
    )
    save_draft('2026-08', '_market',
               {'draft_comment': '본문', 'asset_outlook': {}})
    approve_and_save_final('2026-08', '_market')
    assert 'asset_outlook' not in load_final('2026-08', '_market')


# ────────────────────────── 2. 시드 라이프사이클 ──────────────────────────

def _seed_payload():
    return {
        'period': '2026-08',
        'status': 'draft',
        'sections': {'market': {'_총론': '총론.'}, 'outlook': {'국내주식': '전망.'}},
        'source': {'outlook_period': '9월'},
    }


def test_seed_save_load_roundtrip(tmp_report_root):
    from market_research.report.market_seed import load_seed, save_seed
    save_seed('2026-08', _seed_payload())
    got = load_seed('2026-08')
    assert got['sections']['market']['_총론'] == '총론.'
    assert got['saved_at']


def test_seed_path_is_sidecar_not_overwriting_market(tmp_report_root):
    """`_market.seed.json` 은 `_market.final.json` 과 다른 파일이어야 한다."""
    from market_research.report.market_seed import save_seed, seed_path
    p = save_seed('2026-08', _seed_payload())
    assert p.name == '_market.seed.json'
    assert seed_path('2026-08') == p


def test_load_approved_seed_ignores_draft(tmp_report_root):
    """★ 미승인 시드는 펀드 코멘트 조립에 쓰이지 않는다."""
    from market_research.report.market_seed import (
        approve_seed, load_approved_seed, save_seed,
    )
    save_seed('2026-08', _seed_payload())
    assert load_approved_seed('2026-08') is None

    approve_seed('2026-08')
    approved = load_approved_seed('2026-08')
    assert approved is not None
    assert approved['status'] == 'approved'
    assert approved['approved_at']


def test_approve_missing_seed_returns_none(tmp_report_root):
    from market_research.report.market_seed import approve_seed
    assert approve_seed('2099-01') is None


def test_over_budget_flags_only_excess():
    from market_research.report.market_seed import BUDGET, over_budget
    cls_cap = BUDGET['market']['cls'][2]
    sections = {
        'market': {'국내주식': '가' * (cls_cap + 1), '해외주식': '가' * 100},
        'outlook': {},
    }
    flagged = over_budget(sections)
    assert [(s, k) for s, k, _, _ in flagged] == [('market', '국내주식')]
