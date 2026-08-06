# -*- coding: utf-8 -*-
"""월경계 캐치업 — 전월 09 체인 stale 따라잡기 (2026-08-06).

★ 배경: `daily_update` 는 당월만 처리한다. 월이 바뀌면 전월을 다시 보지 않아
  **월말 발행 리서치가 영구 미반영**으로 남았다. 실측(2026-07): claims 는
  08-03 갱신인데 09 페이지는 07-27 생성분 그대로 → 신한 7/29 「엔 캐리 트레이드
  청산 재발 가능성 점검」이 09 에 없었고, 09 가 debate primary source 라
  7월 시장 코멘트에서도 그 주제가 통째로 빠졌다.

검증 대상:
  1. `_prev_month_str` 연말 롤오버
  2. `_raw_newer_than_adapted` 신선도 판정
  3. `_step_prev_month_catchup` 이 **stale 할 때만** 하위 스텝을 부르고,
     최신이면 no-op (정상 운영일 비용 0)
  4. 캐치업 실패가 당월 파이프라인을 막지 않음 (graceful)

LLM 호출 0 — 하위 스텝은 전부 monkeypatch.
"""
from __future__ import annotations

import pytest

from market_research.pipeline import daily_update as du


# ────────────────────────────── 1. 전월 계산 ──────────────────────────────

@pytest.mark.parametrize('cur,prev', [
    ('2026-08', '2026-07'),
    ('2026-03', '2026-02'),
    ('2026-01', '2025-12'),      # 연말 롤오버
    ('2026-10', '2026-09'),
])
def test_prev_month_str(cur, prev):
    assert du._prev_month_str(cur) == prev


# ────────────────────────── 2. raw > adapted 판정 ──────────────────────────

def test_raw_newer_than_adapted_true_when_adapted_missing(tmp_path, monkeypatch):
    from market_research.collect import naver_research_adapter as nra
    monkeypatch.setattr(nra, 'adapted_path', lambda m: tmp_path / f'{m}.json')
    assert du._raw_newer_than_adapted('2026-07') is True


def test_raw_newer_than_adapted_false_when_adapted_fresh(tmp_path, monkeypatch):
    import time
    from market_research.collect import naver_research_adapter as nra
    raw_dir = tmp_path / 'data' / 'naver_research' / 'raw' / 'cat'
    raw_dir.mkdir(parents=True)
    (raw_dir / '2026-07.json').write_text('[]', encoding='utf-8')
    time.sleep(0.01)
    ap = tmp_path / 'adapted.json'
    ap.write_text('{}', encoding='utf-8')      # raw 보다 나중 → fresh
    monkeypatch.setattr(nra, 'adapted_path', lambda m: ap)
    monkeypatch.setattr(du, 'BASE_DIR', tmp_path)
    assert du._raw_newer_than_adapted('2026-07') is False


# ─────────────────────── 3. 캐치업 호출 조건 ───────────────────────

@pytest.fixture
def spy(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(du, '_step_naver_research_adapter',
                        lambda m: (calls.append(f'adapter:{m}'), {'status': 'ok'})[1])
    monkeypatch.setattr(du, '_step_refine',
                        lambda m: (calls.append(f'refine:{m}'), {'status': 'ok'})[1])
    return calls


def test_skips_adapter_when_raw_not_newer(spy, monkeypatch):
    """raw 가 최신이 아니면 adapter/refine 을 부르지 않는다 (파일 mtime 오염 방지)."""
    monkeypatch.setattr(du, '_raw_newer_than_adapted', lambda m: False)
    monkeypatch.setattr(du, '_step_research_synthesis',
                        lambda m, **k: {'status': 'ok', 'reused': True, 'pages': 8})
    out = du._step_prev_month_catchup('2026-08')
    assert out['month'] == '2026-07'
    assert out['status'] == 'ok'
    assert spy == []                 # adapter/refine 미호출
    assert out['ran'] == []          # 09 도 reused → 아무것도 안 함


def test_runs_adapter_and_refine_when_raw_newer(spy, monkeypatch):
    monkeypatch.setattr(du, '_raw_newer_than_adapted', lambda m: True)
    monkeypatch.setattr(du, '_step_research_synthesis',
                        lambda m, **k: {'status': 'ok', 'reused': True})
    out = du._step_prev_month_catchup('2026-08')
    assert spy == ['adapter:2026-07', 'refine:2026-07']
    assert out['ran'] == ['adapter', 'refine']


def test_records_synthesis_when_regenerated(spy, monkeypatch):
    """09 가 재생성되면 ran 에 기록 — 로그로 캐치업 발생을 알 수 있어야 한다."""
    monkeypatch.setattr(du, '_raw_newer_than_adapted', lambda m: False)
    monkeypatch.setattr(du, '_step_research_synthesis',
                        lambda m, **k: {'status': 'ok', 'reused': False, 'pages': 8})
    out = du._step_prev_month_catchup('2026-08')
    assert out['ran'] == ['research_synthesis']


def test_dry_run_touches_nothing(spy, monkeypatch):
    monkeypatch.setattr(du, '_raw_newer_than_adapted', lambda m: True)
    called = []
    monkeypatch.setattr(du, '_step_research_synthesis',
                        lambda m, **k: called.append(m))
    out = du._step_prev_month_catchup('2026-08', dry_run=True)
    assert out['status'] == 'skip'
    assert spy == [] and called == []


# ──────────────── 4. 커버리지 게이트 (processed_article_ids) ────────────────

def _write_claims(p, processed):
    import json
    p.write_text(json.dumps({'claims': [], 'processed_article_ids': processed}),
                 encoding='utf-8')


def test_unprocessed_count_detects_gap(tmp_path, monkeypatch):
    """★ mtime 게이트만으로는 못 잡는 미처리 기사를 커버리지로 잡는다.

    실측(2026-07): 기사 1,702건 중 processed 1,656 → 미처리 61건,
    그 중 58건이 7/28 이후. claims 가 adapted 보다 나중에 touch 돼
    `_adapted_newer_than_claims` 가 영구 false 였다.
    """
    from market_research.analyze import research_claim_extractor as rce
    cp = tmp_path / 'claims.json'
    _write_claims(cp, ['a1', 'a2'])
    monkeypatch.setattr(rce, 'prep_research_evidence', lambda m, lane: (
        [{'_article_id': 'a1'}, {'_article_id': 'a2'}, {'_article_id': 'a3'}]
        if lane == 'naver_research' else []))
    assert du._unprocessed_article_count('2026-07', cp) == 1      # a3 미처리


def test_unprocessed_count_zero_when_all_covered(tmp_path, monkeypatch):
    from market_research.analyze import research_claim_extractor as rce
    cp = tmp_path / 'claims.json'
    _write_claims(cp, ['a1', 'a2'])
    monkeypatch.setattr(rce, 'prep_research_evidence', lambda m, lane: (
        [{'_article_id': 'a1'}, {'_article_id': 'a2'}] if lane == 'naver_research' else []))
    assert du._unprocessed_article_count('2026-07', cp) == 0


def test_unprocessed_count_legacy_file_returns_zero(tmp_path):
    """processed_article_ids 없는 legacy 파일은 판정 불가 → mtime 게이트에 위임."""
    import json
    cp = tmp_path / 'claims.json'
    cp.write_text(json.dumps({'claims': []}), encoding='utf-8')
    assert du._unprocessed_article_count('2026-07', cp) == 0


def test_unprocessed_count_missing_file(tmp_path):
    assert du._unprocessed_article_count('2026-07', tmp_path / 'nope.json') == 0


def test_unprocessed_count_survives_lane_error(tmp_path, monkeypatch):
    """한 레인이 죽어도 나머지는 센다 — 게이트가 조용히 0 이 되면 안 된다."""
    from market_research.analyze import research_claim_extractor as rce
    cp = tmp_path / 'claims.json'
    _write_claims(cp, ['a1'])

    def _lane(m, lane):
        if lane == 'monygeek':
            raise RuntimeError('boom')
        return [{'_article_id': 'zz'}] if lane == 'naver_research' else []
    monkeypatch.setattr(rce, 'prep_research_evidence', _lane)
    assert du._unprocessed_article_count('2026-07', cp) == 1


def test_failure_is_graceful(monkeypatch):
    """★ 캐치업이 죽어도 당월 파이프라인은 계속돼야 한다."""
    monkeypatch.setattr(du, '_raw_newer_than_adapted', lambda m: False)

    def _boom(m, **k):
        raise RuntimeError('P4 consensus 실패')
    monkeypatch.setattr(du, '_step_research_synthesis', _boom)
    out = du._step_prev_month_catchup('2026-08')
    assert out['status'] == 'error'
    assert 'P4 consensus 실패' in out['error']
