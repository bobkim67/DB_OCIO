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


def test_fx_is_not_split_out():
    """FX 는 자산군에 포함(fx_split=False) — 껍데기 0.00% 행이 문장에 찍히면 안 된다.

    2JM23 2026-07 실측: fx_split=False 면 환효과가 해외주식·대체에 녹아 FX=0.00.
    """
    pa = {'국내주식': -2.93, '해외주식': -3.77, '국내채권': -0.17, '대체': -0.81, 'FX': 0.0}
    s = build_perf_sentence('7월 중', {'return': -7.78}, pa)
    assert 'FX' not in s
    assert '해외주식 -3.77%' in s      # 환효과 포함된 값


def test_warns_when_fx_is_material():
    """실제 FX 상품을 들고 있으면 조용히 사라지지 않게 경고."""
    w: list[str] = []
    build_perf_sentence('7월 중', {'return': 1.0}, {'국내주식': 1.0, 'FX': -4.12}, w)
    assert w and 'FX' in w[0]


def test_drops_rounding_zero_classes():
    """미보유(반올림 0.00%) 자산군은 뺀다 — 발송본 예시에 해외채권 행이 없다."""
    pa = {'국내주식': 1.2, '해외채권': 0.0, '대체': 0.004}
    s = build_perf_sentence('7월 중', {'return': 1.2}, pa)
    assert '해외채권' not in s and '대체' not in s


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
    ('월별', 7, 3, '7월 중'),      # ★ API 가 넘기는 실제 월간 mode 값 ('월간' 아님)
    ('분기', 6, 2, '2분기 중'),
    ('QTD', 8, 3, '분기 중'),
    ('HTD', 8, 4, '반기 중'),
    ('YTD', 8, 4, '연초 이후'),
])
def test_period_label(mode, month, quarter, expect):
    from datetime import date
    assert _perf_period_label(mode, date(2026, month, 30), quarter) == expect


def test_monthly_mode_value_matches_api():
    """`_PERIOD_PATTERNS['월간']` 이 넘기는 mode 가 월간으로 해석돼야 한다.

    회귀 방어: 종전엔 '월간'을 직접 비교해서 실제 값('월별')이 안 걸렸고,
    7월 코멘트가 "당 기간 펀드는…" 으로 나왔다.
    """
    from datetime import date
    from api.routers.admin_funds import _PERIOD_PATTERNS
    monthly_mode = _PERIOD_PATTERNS['월간'][1]
    assert _perf_period_label(monthly_mode, date(2026, 7, 31), 3) == '7월 중'


def test_period_label_falls_back_without_date():
    assert _perf_period_label('월별', None, 3) == '당 기간'


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


# ── 운용계획 블록 규칙 (숫자·종목명·정도부사 금지) ──

def test_plan_rule_flags_numbers_names_adverbs():
    from market_research.report.comment_engine import check_block_rules
    v = check_block_rules('2JM23', '계획',
                          'ACE 200 비중을 11.1%에서 27.7%로 대폭 확대하였습니다.')
    joined = ' | '.join(v)
    assert '숫자' in joined and '정도부사' in joined and '종목명' in joined


def test_plan_rule_passes_clean_text():
    from market_research.report.comment_engine import check_block_rules
    assert check_block_rules(
        '2JM23', '계획',
        '국내주식 비중을 확대하였습니다. 재원은 대체 축소로 마련하였습니다.') == []


def test_plan_rule_scoped_to_2jm23_plan_block():
    """다른 펀드·다른 블록은 규칙 대상이 아니다 (골든 불변)."""
    from market_research.report.comment_engine import check_block_rules
    bad = 'ACE 200 비중을 11.1%에서 27.7%로 대폭 확대'
    assert check_block_rules('4JM12', '계획', bad) == []
    assert check_block_rules('2JM23', '성과', bad) == []


def test_plan_rule_is_injected_into_prompt_spec():
    from market_research.report.comment_engine import BLOCK_EXTRA_RULES
    rule = BLOCK_EXTRA_RULES[('2JM23', '계획')]
    assert '숫자' in rule and '종목명' in rule and '대폭' in rule


def test_compress_cache_key_includes_cap():
    """캡이 다르면 다른 캐시 슬롯 — 400자본이 300자 요청에 재사용되면 안 된다."""
    from market_research.report.market_seed import _compact_cache_path
    a = _compact_cache_path('본문', 400, 'm')
    b = _compact_cache_path('본문', 300, 'm')
    assert a != b
