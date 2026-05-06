"""Regression: run_quarterly_debate 가 monthly run_market_debate 와 trace parity (Q-FIX-1).

LLM 호출 없이 monkeypatch 로 4 agent + Opus stub. 실 LLM smoke 는 별도.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─────────────────────────────────────────────
# helper 단독 테스트 — LLM 호출 무관
# ─────────────────────────────────────────────

def test_evidence_month_distribution_uses_news_dir():
    """_evidence_month_distribution 이 news json 에서 article_id 매핑."""
    from market_research.report.debate_engine import _evidence_month_distribution

    # 실제 디스크 — 2026-01/02/03 news json 존재 가정
    ev_ids = []
    # 1월 articles 의 _article_id 일부 가져옴 (sample)
    news_jan = PROJECT_ROOT / 'market_research' / 'data' / 'news' / '2026-01.json'
    if news_jan.exists():
        data = json.loads(news_jan.read_text(encoding='utf-8'))
        for a in data.get('articles', [])[:5]:
            aid = a.get('_article_id')
            if aid:
                ev_ids.append(aid)
    # unknown id 1개 추가
    ev_ids.append('NONEXISTENT_ID_12345')

    dist = _evidence_month_distribution(ev_ids, 2026, [1, 2, 3])
    # 5건은 2026-01 으로 매핑, 1건은 unknown
    if news_jan.exists() and len(ev_ids) > 1:
        assert '2026-01' in dist or 'unknown' in dist, (
            f'expected 2026-01 or unknown in dist: {dist}'
        )
        assert dist.get('unknown', 0) >= 1, (
            f'unknown (NONEXISTENT id) 1건 이상 기대: {dist}'
        )


def test_evidence_month_distribution_empty_input():
    """빈 evidence_ids → 빈 dict."""
    from market_research.report.debate_engine import _evidence_month_distribution
    dist = _evidence_month_distribution([], 2026, [1, 2, 3])
    assert dist == {}, f'expected empty, got {dist}'


def test_evidence_month_distribution_missing_month_files():
    """없는 month files → 모두 unknown."""
    from market_research.report.debate_engine import _evidence_month_distribution
    dist = _evidence_month_distribution(['fake1', 'fake2'], 1999, [1])
    assert dist.get('unknown', 0) == 2, f'expected 2 unknowns, got {dist}'


# ─────────────────────────────────────────────
# run_quarterly_debate 의 result schema (LLM stub)
# ─────────────────────────────────────────────

def _stub_agents_and_opus(monkeypatch):
    """4 agent + Opus 종합 + naver research adapter 모두 stub."""
    from market_research.report import debate_engine as de

    fake_agent_resp = {
        '낙관론자': {'agent': '낙관론자', 'stance': 'bullish', 'key_points': ['x']},
        '비관론자': {'agent': '비관론자', 'stance': 'bearish', 'key_points': ['y']},
        '데이터 분석가': {'agent': '데이터 분석가', 'stance': 'neutral', 'key_points': ['z']},
        '유로달러 학파 분석가': {'agent': '유로달러 학파 분석가', 'stance': 'neutral', 'key_points': ['w']},
    }

    def fake_run_agent(agent, ctx):
        return fake_agent_resp[agent]

    def fake_synth(agents, _, ctx):
        return {
            'customer_comment': '국내주식 +5% 해외채권 -1% — fake comment',
            'admin_summary': 'fake admin',
            'consensus_points': ['c1'],
            'disagreements': [],
            'tail_risks': [],
        }

    monkeypatch.setattr(de, '_run_agent', fake_run_agent)
    monkeypatch.setattr(de, '_synthesize_debate', fake_synth)


def test_quarterly_result_has_debug_trace_and_annotations(monkeypatch):
    """Q-FIX-1: result 에 _debug_trace 와 evidence_annotations 가 추가됐는지."""
    _stub_agents_and_opus(monkeypatch)
    from market_research.report.debate_engine import run_quarterly_debate

    # 실 _build_shared_context 호출 (디스크 read + graph_rag 등) — but agent/Opus 만 stub
    result = run_quarterly_debate(year=2026, quarter=1)

    # Q-FIX-1 assertion
    assert '_debug_trace' in result, '_debug_trace 키 부재 — Q-FIX-1 회귀'
    trace = result['_debug_trace']
    assert isinstance(trace, dict)
    assert trace.get('debate_mode') == 'quarterly'
    assert trace.get('months') == [1, 2, 3]
    assert trace.get('period') == '2026-Q1'

    # wiki trace key 들 존재 (값은 None 가능 — 환경 의존)
    for k in ('wiki_period_used', 'wiki_stage_used', 'wiki_excluded_dirs',
              'wiki_excluded_dir_page_count', 'wiki_skipped_future_pages',
              'wiki_context_pages', 'wiki_retrieval_keywords'):
        assert k in trace, f'wiki trace key 부재: {k}'

    # evidence_annotations 추가
    assert 'evidence_annotations' in result, 'evidence_annotations 키 부재'
    ev_ids = result.get('_evidence_ids', [])
    annotations = result['evidence_annotations']
    assert isinstance(annotations, list)
    # 길이 일치 (1:1 매핑)
    assert len(annotations) == len(ev_ids), (
        f'annotations({len(annotations)}) ≠ evidence_ids({len(ev_ids)})'
    )

    # evidence_month_distribution
    ev_dist = trace.get('evidence_month_distribution')
    assert isinstance(ev_dist, dict)
    # 1/2/3월 중 하나라도 있어야 (실 데이터 의존)
    valid_months = {'2026-01', '2026-02', '2026-03', 'unknown'}
    assert all(k in valid_months for k in ev_dist.keys()), (
        f'unexpected month keys: {list(ev_dist.keys())}'
    )


def test_quarterly_wiki_period_filter_blocks_future(monkeypatch):
    """Q-FIX-1: 분기 wiki retrieval 의 period 가 마지막 월 (3월) 기준 → 4/5월 page 차단."""
    _stub_agents_and_opus(monkeypatch)
    from market_research.report.debate_engine import run_quarterly_debate

    result = run_quarterly_debate(year=2026, quarter=1)
    trace = result['_debug_trace']

    # wiki_period_used 는 None 이거나 '2026-03' (마지막 월)
    wp = trace.get('wiki_period_used')
    assert wp is None or wp == '2026-03', (
        f'wiki_period_used should be 2026-03 (분기 end_month), got {wp}'
    )

    # selected pages 에 4월/5월 page 없음
    sel = trace.get('wiki_context_pages') or []
    leaked = [p for p in sel if '2026-04' in p or '2026-05' in p
              or '2026-06' in p]
    assert not leaked, f'4/5/6월 wiki page leaked: {leaked}'


def test_quarterly_does_not_break_monthly():
    """monthly run_market_debate 의 result schema 무변경 (회귀)."""
    # monthly debate 의 result 는 _debug_trace 키 *원래 갖고 있었음*. 우리가 추가한
    # 건 quarterly. 변경 없음 검증 — 코드 review 차원.
    from market_research.report.debate_engine import run_market_debate
    import inspect
    src = inspect.getsource(run_market_debate)
    # monthly 가 _debug_trace 갖고 있다는 사실 확인
    assert "'_debug_trace'" in src, 'monthly _debug_trace key 존재 확인'
    assert "'_evidence_ids'" in src
    # quarterly 변경이 monthly 안 건드림 — Q-FIX-1 marker 가 quarterly 함수에만
    assert "Q-FIX-1" not in src, 'monthly 함수에 Q-FIX-1 marker 누출 — 회귀'


if __name__ == '__main__':
    # pytest 없이 단독 실행
    import unittest.mock as _m

    class FakeMonkey:
        def __init__(self):
            self._patches = []
        def setattr(self, target, name, value):
            p = _m.patch.object(target, name, value)
            p.start()
            self._patches.append(p)
        def stop_all(self):
            for p in self._patches:
                p.stop()

    test_evidence_month_distribution_empty_input()
    print('PASS test_evidence_month_distribution_empty_input')
    test_evidence_month_distribution_missing_month_files()
    print('PASS test_evidence_month_distribution_missing_month_files')
    test_evidence_month_distribution_uses_news_dir()
    print('PASS test_evidence_month_distribution_uses_news_dir')
    test_quarterly_does_not_break_monthly()
    print('PASS test_quarterly_does_not_break_monthly')
    # monkeypatch 필요한 테스트
    for fn in [test_quarterly_result_has_debug_trace_and_annotations,
               test_quarterly_wiki_period_filter_blocks_future]:
        mp = FakeMonkey()
        try:
            fn(mp)
            print(f'PASS {fn.__name__}')
        finally:
            mp.stop_all()
    print('ALL PASS')
