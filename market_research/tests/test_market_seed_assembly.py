# -*- coding: utf-8 -*-
"""자산군 시드 — 어휘 정규화 · 결정론적 조립 · 포맷 골격 (2026-08-05).

검증 대상:
  1. core.asset_class  — PA 어휘('대체')와 거래 어휘('대체투자') 정규화.
     ★ 회귀 방어: 금을 **보유만 하고 매매하지 않은** 펀드가 '대체투자' 미편입으로
       판정되던 버그 (fund_comment_service 의 상수 집합이 거래 어휘였다).
  2. market_seed.assemble — 보유 자산군만, 고정 순서, 미보유는 삭제만.
     전망은 첫 문장에만 기간 라벨.
  3. comment_engine.parse_seeded_blocks / assemble_seeded_comment —
     포맷 A/C/D/K 골격이 2026-07 승인본과 동일한 구조인지.

LLM 호출 0.
"""
from __future__ import annotations

import pytest

from market_research.core.asset_class import (
    CANONICAL_CLASSES, active_classes, excluded_classes, normalize, ordered,
)
from market_research.report.comment_engine import (
    SEEDED_BLOCKS, assemble_seeded_comment, parse_seeded_blocks,
)
from market_research.report.market_seed import (
    TOTAL_KEY, assemble, seed_coverage, strip_period_prefix,
)

# compute_single_port_pa(방법3) asset_summary 자산군 실측 라벨
PA_HOLDINGS = {
    '포트폴리오': 0.0, '국내주식': 12.0, '해외주식': 30.0, '국내채권': 40.0,
    '해외채권': 5.0, '대체': 6.0, 'FX': 1.0, '유동성및기타': 6.0,
}
# load_fund_net_trades 실측 라벨 (어휘가 다르다)
TRADE_KEYS = {'유동성': 1, '해외주식': 1, '국내주식': 1, '국내채권': 1,
              '대체투자': 1, 'FX': 1, '해외채권': 1}


# ──────────────────────────────── 1. 어휘 정규화 ────────────────────────────

def test_normalize_maps_both_vocabularies():
    assert normalize('대체') == '대체'
    assert normalize('대체투자') == '대체'      # 거래 어휘
    assert normalize('원자재') == '대체'
    assert normalize('환율(FX)') == 'FX'        # amc 어휘


@pytest.mark.parametrize('label', ['유동성', '유동성및기타', '포트폴리오', '모펀드', '보수비용'])
def test_normalize_drops_non_narrative(label):
    assert normalize(label) is None


def test_active_classes_unions_holdings_and_trades():
    assert active_classes(PA_HOLDINGS, TRADE_KEYS) == set(CANONICAL_CLASSES)


def test_gold_held_but_not_traded_is_still_active():
    """★ 회귀: 종전엔 '대체투자' 가 거래에만 있어서, 매매 없는 달에 미편입 판정."""
    trades_without_gold = {'유동성': 1, '국내주식': 1}
    assert '대체' in active_classes(PA_HOLDINGS, trades_without_gold)
    assert '대체' not in excluded_classes(PA_HOLDINGS, trades_without_gold)


def test_gold_truly_absent_is_excluded():
    no_gold = {k: v for k, v in PA_HOLDINGS.items() if k != '대체'}
    assert excluded_classes(no_gold, {'국내주식': 1}) == {'대체'}


def test_narrative_orders_differ_between_sections():
    """시장동향은 해외주식 먼저, 전망은 국내주식 먼저 (2026-07 승인본 관행)."""
    allc = set(CANONICAL_CLASSES)
    assert ordered(allc, 'market')[0] == '해외주식'
    assert ordered(allc, 'outlook')[0] == '국내주식'


# ──────────────────────────────── 2. 시드 조립 ──────────────────────────────

SEED = {
    'period': '2026-07',
    'status': 'approved',
    'source': {'outlook_period': '8월'},
    'sections': {
        'market': {
            TOTAL_KEY: '총론입니다.',
            '국내주식': '국내주식 시장동향입니다.',
            '해외주식': '해외주식 시장동향입니다.',
            '국내채권': '국내채권 시장동향입니다.',
            '해외채권': '해외채권 시장동향입니다.',
            '대체': '금은 보합에 그쳤습니다.',
            'FX': 'FX 시장동향입니다.',
        },
        'outlook': {
            '국내주식': '국내주식시장은 변동성이 지속될 것으로 예상합니다.',
            '해외주식': '해외주식시장은 회복에 시간이 필요할 것으로 보입니다.',
            '국내채권': '국내채권은 상방 압력이 이어질 것으로 예상합니다.',
            '해외채권': '해외채권은 부진이 이어질 가능성이 있습니다.',
            '대체': '금은 방향성이 제한적일 것으로 예상합니다.',
            'FX': '원화는 되돌림 위험을 열어둘 필요가 있습니다.',
        },
    },
}


def test_market_assembly_starts_with_total_then_fixed_order():
    out = assemble(SEED, set(CANONICAL_CLASSES), 'market')
    assert out.startswith('총론입니다.')
    # 해외주식 → 국내주식 순 (MARKET_ORDER)
    assert out.index('해외주식 시장동향') < out.index('국내주식 시장동향')


def test_outlook_labels_only_first_sentence():
    out = assemble(SEED, set(CANONICAL_CLASSES), 'outlook')
    assert out.startswith('8월 국내주식시장은')
    assert out.count('8월') == 1


def test_outlook_label_moves_when_first_class_absent():
    """국내주식 미보유면 다음 자산군이 라벨을 받는다."""
    out = assemble(SEED, set(CANONICAL_CLASSES) - {'국내주식'}, 'outlook')
    assert out.startswith('8월 해외주식시장은')


def test_missing_class_is_deleted_not_substituted():
    """★ 사용자 확정: 미보유 자산군은 삭제만. 대체 문장을 넣지 않는다."""
    full = assemble(SEED, set(CANONICAL_CLASSES), 'market')
    no_gold = assemble(SEED, set(CANONICAL_CLASSES) - {'대체'}, 'market')
    assert '금은 보합에 그쳤습니다.' in full
    assert '금은 보합에 그쳤습니다.' not in no_gold
    # 남은 문장은 글자 그대로 동일 — 펀드 간 편차 0 이라는 것이 이 기능의 요지
    assert no_gold == full.replace(' 금은 보합에 그쳤습니다.', '')


def test_two_funds_share_byte_identical_sentences():
    a = assemble(SEED, set(CANONICAL_CLASSES), 'market')
    b = assemble(SEED, set(CANONICAL_CLASSES) - {'대체'}, 'market')
    common = [s for s in b.split(' ') if s]
    assert all(s in a for s in common)


def test_empty_active_yields_only_total():
    assert assemble(SEED, set(), 'market') == '총론입니다.'
    assert assemble(SEED, set(), 'outlook') == ''


def test_seed_coverage_reports_missing():
    sparse = {**SEED, 'sections': {**SEED['sections'],
                                   'market': {TOTAL_KEY: '총론.', '국내주식': '있음.'}}}
    cov = seed_coverage(sparse, {'국내주식', '대체'}, 'market')
    assert cov['missing'] == ['대체']


@pytest.mark.parametrize('raw,expect', [
    ('8월 국내주식시장은 …', '국내주식시장은 …'),
    ('4분기 채권은 …', '채권은 …'),
    ('2026년 하반기 금은 …', '금은 …'),
    ('국내주식시장은 …', '국내주식시장은 …'),      # 라벨 없으면 그대로
])
def test_strip_period_prefix(raw, expect):
    assert strip_period_prefix(raw) == expect


# ──────────────────────────────── 3. 포맷 조립 ──────────────────────────────

def _blocks(fmt):
    return {n: f'{n} 본문입니다.' for n, _ in SEEDED_BLOCKS[fmt]}


@pytest.mark.parametrize('fmt', ['A', 'C', 'D', 'K'])
def test_parse_roundtrip(fmt):
    names = [n for n, _ in SEEDED_BLOCKS[fmt]]
    text = '\n'.join(f'<<<{n}>>>\n{n} 본문입니다.' for n in names)
    assert parse_seeded_blocks(text, fmt) == _blocks(fmt)


def test_parse_returns_none_when_block_missing():
    """일부 블록만 오면 None → 호출부가 레거시 전문 생성으로 폴백한다."""
    assert parse_seeded_blocks('<<<성과>>>\n본문만 있음', 'A') is None


def test_parse_strips_markdown_leftovers():
    got = parse_seeded_blocks(
        '<<<성과>>>\n- **성과** 본문\n<<<매니저>>>\n매니저 본문', 'A')
    assert got == {'성과': '성과 본문', '매니저': '매니저 본문'}


def test_format_A_skeleton_matches_approved():
    """2026-07 08N81 승인본 골격 — 탭 들여쓰기, 섹션 사이 빈 줄."""
    out = assemble_seeded_comment('A', '시장동향', '전망', _blocks('A'))
    assert out.split('\n') == [
        '■ 월간 시장동향과 펀드의 움직임',
        '\t시장동향',
        '\t성과 본문입니다.',
        '',
        '■ 향후 시장전망',
        '\t전망',
        '',
        '■ 매니저 코멘트',
        '\t매니저 본문입니다.',
    ]


def test_format_C_skeleton_matches_approved():
    """2026-07 07G04 승인본 골격 — 한 칸 들여쓰기."""
    out = assemble_seeded_comment('C', '시장동향', '전망', _blocks('C'))
    assert out.split('\n') == [
        '[운용경과]', '1. 시장 동향', ' 시장동향', '',
        '2. 운용경과', ' 성과 본문입니다.', '',
        '[운용계획]', '1. 시장 전망', ' 전망', '',
        '2. 포지션', ' 포지션 본문입니다.',
    ]


def test_format_D_skeleton_matches_approved():
    """2026-07 4JM12 승인본 골격 — 모든 블록 사이 빈 줄, 들여쓰기 없음."""
    out = assemble_seeded_comment('D', '시장동향', '전망', _blocks('D'))
    assert out.split('\n') == [
        '1. 운용성과 요약', '', '시장동향', '', '성과 본문입니다.', '',
        '2. 시장환경 분석 및 펀드운용계획', '',
        '시장환경 분석: 전망', '', '펀드 운용 계획: 계획 본문입니다.',
    ]


def test_format_K_bullets_and_sub_line():
    out = assemble_seeded_comment('K', '시장동향', '전망', _blocks('K'),
                                  sub_line='비중은 48:52 수준으로 유지하였습니다.')
    lines = out.split('\n')
    assert lines[0] == '- 시장동향'
    assert lines[1] == '- 매매 본문입니다.'
    assert lines[2] == '- 성과 본문입니다.'
    assert lines[3] == '비중은 48:52 수준으로 유지하였습니다.'
    assert lines[4] == ''            # B29 / B33 셀 경계
    assert lines[5] == '- 전망'
    assert lines[6] == '- 계획 본문입니다.'


def test_unknown_format_raises():
    with pytest.raises(ValueError):
        assemble_seeded_comment('Z', 'm', 'o', {})


# ──────────────── 5. 시장 레벨 사실 주입 (2026-09-01) ────────────────
# ★ 회귀 방어: 규칙 4 가 "레벨로 쓰라"고 권하는데 debate 본문에는 변동률만 있어
#   모델이 레벨을 지어냈다 — 8월말 달러/원 1,368.60 을 "1,530원대", KOSPI 월중
#   최고 6,977.9 를 "7,200 터치"로 썼다. DB 실측 레벨을 사실로 주입해 막는다.

def test_period_bounds_covers_all_period_kinds():
    import datetime as dt

    from market_research.report.market_seed import _period_bounds

    # 월간 — 기초는 **전월 말일**(기간 시작 하루 전이 아니라 직전 기간의 끝)
    assert _period_bounds('2026-08') == (dt.date(2026, 7, 31), dt.date(2026, 8, 31))
    assert _period_bounds('2026-01') == (dt.date(2025, 12, 31), dt.date(2026, 1, 31))
    # 분기 — Q1 의 기초는 전년 말
    assert _period_bounds('2026-Q2') == (dt.date(2026, 3, 31), dt.date(2026, 6, 30))
    assert _period_bounds('2026-Q1')[0] == dt.date(2025, 12, 31)
    # TD 계열은 종료일이 오늘 (미래 월말을 잡으면 안 된다)
    today = dt.date.today()
    assert _period_bounds('2026-Q3.QTD') == (dt.date(2026, 6, 30), today)
    assert _period_bounds('2026-H2.HTD') == (dt.date(2026, 6, 30), today)
    assert _period_bounds('2026-H1.HTD')[0] == dt.date(2025, 12, 31)
    assert _period_bounds('2026-YTD') == (dt.date(2025, 12, 31), today)
    # 알 수 없는 키는 None — 호출부가 블록 없이 진행한다
    assert _period_bounds('헛소리') is None
    assert _period_bounds('') is None


def test_month_bound_is_clamped_to_today():
    """진행 중인 달은 종료일이 미래 월말이 아니라 오늘이다."""
    import datetime as dt

    from market_research.report.market_seed import _period_bounds

    today = dt.date.today()
    cur = f'{today.year:04d}-{today.month:02d}'
    assert _period_bounds(cur)[1] == today


def test_level_facts_go_into_prompt_and_absence_is_safe():
    from market_research.report.market_seed import _build_prompt

    facts = ['- KOSPI: 6,595.45 (07/31) → 6,820.02 (08/31) = +3.40%',
             '- 달러/원: 1,425.70 (07/31) → 1,368.60 (08/31) = -4.01%']
    kw = dict(market_body='본문', next_label='9월', consensus=[], tail_risks=[],
              have_outlook=True, period_label='2026년 8월')
    with_facts = _build_prompt(levels=facts, **kw)
    assert '## 시장 레벨' in with_facts
    for f in facts:
        assert f in with_facts
    # 사실이 없으면 블록도 없다 — 규칙이 "레벨을 쓰지 말라"로 받는다
    without = _build_prompt(levels=None, **kw)
    assert '## 시장 레벨' not in without
    assert '레벨을 아예 쓰지 말고' in without


def test_level_facts_fail_open_when_db_is_down(monkeypatch):
    """DB 가 죽어도 시드 생성은 계속된다 (블록만 빠진다)."""
    import market_research.report.market_seed as ms

    def boom(*a, **k):
        raise RuntimeError('DB down')

    monkeypatch.setattr('modules.data_loader.get_pandas_connection', boom)
    assert ms._market_level_facts('2026-08') is None


def test_level_sql_parenthesizes_the_or():
    """⚠ OR 를 안 묶으면 AND 가 먼저 걸려 한쪽 시리즈가 전 이력을 긁어온다."""
    import inspect

    import market_research.report.market_seed as ms

    src = inspect.getsource(ms._market_level_facts)
    assert 'WHERE ({pairs})' in src
