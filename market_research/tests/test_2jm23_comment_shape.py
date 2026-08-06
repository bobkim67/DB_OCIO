# -*- coding: utf-8 -*-
"""2JM23 코멘트 형태 override — 시장동향 400자 캡 · 성과 문장 코드 고정 (2026-08-06).

신한라이프 발송본은 슬라이드 텍스트 상자가 좁아 공통 시드 문단(600~700자)이 통째로
들어가지 않는다. 그래서 **이 펀드만**:
  1. 시장동향(공통 시드 조립분)을 400자 이하로 재압축
  2. 성과 문단을 LLM 이 아니라 코드가 결정론적으로 작성 (수치 나열 한 문장)

LLM 호출 0 — 재압축은 cap 이하 입력(no-op 경로)만 검증한다.
"""
from __future__ import annotations

import pytest

from market_research.core.constants import (
    FIXED_PERF_SENTENCE_FUNDS, MARKET_PARA_CAP, PERF_SENTENCE_EXCLUDE,
)
from market_research.report.comment_engine import build_perf_sentence
from market_research.report.fund_comment_service import _perf_period_label
from market_research.report.market_seed import compress_market_paragraph


# ── 설정 결선 ──

def test_only_2jm23_is_overridden():
    """다른 펀드는 종전 경로 그대로여야 한다 (골든 불변)."""
    assert set(MARKET_PARA_CAP) == {'2JM23'}
    assert FIXED_PERF_SENTENCE_FUNDS == {'2JM23'}
    assert MARKET_PARA_CAP['2JM23'] == 400


# ── 성과 문장 (코드 고정) ──

def test_matches_sent_report_wording():
    """2026-06 발송본 문장을 글자 그대로 재현해야 한다 (사용자 제시 원문)."""
    pa = {'국내주식': 3.90, '해외주식': 0.42, '국내채권': 0.11, '대체': -1.73}
    assert build_perf_sentence('6월 중', {'return': 2.44}, pa) == (
        '6월 중 펀드는 +2.44%의 성과를 기록하였으며, 자산군별 성과기여도는 '
        '국내주식 +3.90%, 해외주식 +0.42%, 국내채권 +0.11%, 대체 -1.73% '
        '이었습니다.'
    )


def test_fixed_canonical_order_not_by_size():
    """자산군은 **고정 순서**. 기여도 크기순이면 매달 순서가 뒤바뀐다.

    발송본 2·5월 예시가 크기순이 아니라는 점이 근거다 (6월 예시는 우연히 둘 다 만족).
    """
    pa = {'국내채권': -0.28, '해외주식': -4.55, '대체': -0.55, '국내주식': -3.07}
    s = build_perf_sentence('7월 중', {'return': -8.55}, pa)
    order = [s.index(c) for c in ('국내주식', '해외주식', '국내채권', '대체')]
    assert order == sorted(order), s


def test_unknown_class_is_appended_not_dropped():
    """canonical 에 없는 라벨도 조용히 사라지면 안 된다."""
    s = build_perf_sentence('7월 중', {'return': 1.0},
                            {'국내주식': 1.2, '신규자산군': -0.2})
    assert '신규자산군 -0.20%' in s
    assert s.index('국내주식') < s.index('신규자산군')


def test_excludes_liquidity_and_fee():
    """유동성·보수비용 제외 — 기여도 합이 펀드 수익률과 어긋나지만 발송본 관행."""
    pa = {'국내주식': 1.0, '유동성및기타': -0.05, '유동성': -0.01, '보수비용': -0.06}
    s = build_perf_sentence('7월 중', {'return': 0.88}, pa)
    assert '국내주식 +1.00%' in s
    for cls in PERF_SENTENCE_EXCLUDE:
        assert cls not in s


def test_no_commentary_appended():
    """'여기까지만' — 기여도 나열 뒤에 해설 문장을 붙이지 않는다."""
    s = build_perf_sentence('7월 중', {'return': -8.55}, {'국내주식': -3.07})
    assert s.endswith('이었습니다.')
    assert s.count('다.') == 1          # 문장 1개


def test_returns_none_without_numbers():
    """수치가 없으면 None → 호출부가 LLM 블록을 그대로 쓴다(무중단)."""
    assert build_perf_sentence('7월 중', None, {'국내주식': 1.0}) is None
    assert build_perf_sentence('7월 중', {'return': 1.0}, {}) is None
    assert build_perf_sentence('7월 중', {'return': 1.0},
                               {'유동성': -0.1}) is None   # 제외 후 남는 게 없음


def test_accepts_bare_float_return():
    assert build_perf_sentence('7월 중', -8.55, {'국내주식': -3.07}).startswith(
        '7월 중 펀드는 -8.55%')


# ── 기간 라벨 ──

@pytest.mark.parametrize('mode,month,quarter,expect', [
    ('월간', 7, 3, '7월 중'),
    ('분기', 6, 2, '2분기 중'),
    ('QTD', 8, 3, '분기 중'),
    ('HTD', 8, 4, '반기 중'),
    ('YTD', 8, 4, '연초 이후'),
])
def test_period_label(mode, month, quarter, expect):
    from datetime import date
    assert _perf_period_label(mode, date(2026, month, 30), quarter) == expect


def test_period_label_falls_back_without_date():
    assert _perf_period_label('월간', None, 3) == '당 기간'


# ── 400자 재압축 (LLM 미호출 경로) ──

def test_compress_noop_when_within_cap():
    """이미 캡 이하면 LLM 을 부르지 않고 원문 그대로."""
    body = '가' * 300
    r = compress_market_paragraph(body, 400)
    assert r['text'] == body
    assert r['applied'] is True
    assert r['reason'] == 'already_within_cap'
    assert r['cost'] == 0.0


def test_compress_empty_is_safe():
    r = compress_market_paragraph('', 400)
    assert r['applied'] is False and r['text'] == ''


def test_compress_cache_key_includes_cap():
    """캡이 다르면 다른 캐시 슬롯 — 400자본이 300자 요청에 재사용되면 안 된다."""
    from market_research.report.market_seed import _compact_cache_path
    a = _compact_cache_path('본문', 400, 'm')
    b = _compact_cache_path('본문', 300, 'm')
    assert a != b
