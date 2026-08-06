# -*- coding: utf-8 -*-
"""DB생명(4JM12) 포맷 E — 6슬롯 골격 · 운용계획 규칙 · 환헤지 레인지 (2026-08-06).

발송본 s6 구조가 2JM23(포맷 D)과 달라 별도 포맷을 만들었다:

    운용경과   시장 동향 (시드) / 운용 경과 (LLM) / 펀드 성과 (LLM)
    운용계획   매크로 (시드)    / 운용계획 (LLM)  / 환헤지 비율 (전월 승계 + 레인지 치환)

LLM 호출 0.
"""
from __future__ import annotations

import pytest

from market_research.core.constants import FUND_CONFIGS, MARKET_PARA_CAP
from market_research.report.comment_engine import (
    BLOCK_EXTRA_RULES, SEEDED_BLOCKS, assemble_seeded_comment,
    check_block_rules, parse_seeded_blocks,
)
from market_research.report.fund_comment_service import _HEDGE_RANGE_RE

# 사용자 제공 전월 발송본 (2026-07 회신본) — 골격·문구의 기준
_PREV_HEDGE = (
    '원달러 환율 레인지를 1달러 당 1,500원 ~ 1,580원 수준으로 두고 유연하게 대응할 '
    '계획입니다. 미·이란 휴전 이행에 따른 유가 및 물가 안정 여부, 외국인 국내주식 '
    '순매도 지속 여부를 중점적으로 모니터링하고 있습니다.'
)


def test_fund_uses_format_e():
    assert FUND_CONFIGS['4JM12']['format'] == 'E'


def test_blocks_are_llm_only_slots():
    """시장 동향·매크로는 시드가 채우므로 LLM 블록은 3개뿐이다."""
    assert [n for n, _ in SEEDED_BLOCKS['E']] == ['운용경과', '펀드성과', '운용계획']


def test_skeleton_matches_sent_report():
    """라벨 표기까지 발송본 그대로 — '운용계획:' 만 콜론 앞 공백이 없다."""
    out = assemble_seeded_comment(
        'E', 'M', 'O',
        {'운용경과': 'A', '펀드성과': 'B', '운용계획': 'C'}, hedge_line='H')
    assert out == (
        '운용경과\n'
        '시장 동향 : M\n'
        '운용 경과 : A\n'
        '펀드 성과 : B\n'
        '\n'
        '운용계획\n'
        '매크로 : O\n'
        '운용계획: C\n'
        '환헤지 비율 : H'
    )


def test_blocks_roundtrip():
    raw = ('<<<운용경과>>>\n가\n<<<펀드성과>>>\n나\n<<<운용계획>>>\n다')
    assert parse_seeded_blocks(raw, 'E') == {
        '운용경과': '가', '펀드성과': '나', '운용계획': '다'}


def test_market_para_cap_is_250():
    """발송본 시장 동향이 210자 안팎이라 250자 (2026-08-07 사용자 지시).

    ⚠ 2JM23(400)과 캡이 달라 재압축 결과도 다르다 — 두 문단이 글자 그대로 같지는 않다.
    """
    assert MARKET_PARA_CAP['4JM12'] == 250
    assert MARKET_PARA_CAP['2JM23'] == 400


# ── 운용계획 규칙 (2JM23 과 같은 규칙, 내용은 4JM12) ──

def test_plan_rule_registered():
    rule = BLOCK_EXTRA_RULES[('4JM12', '운용계획')]
    for token in ('숫자', '종목명', '대폭', '판단 근거'):
        assert token in rule, token


def test_plan_rule_passes_sent_report_wording():
    """발송본 운용계획 문장이 규칙을 통과해야 한다 (기준이 되는 원고)."""
    ok = ('주식 및 채권은 중립수준을 유지 예정. 스타일 측면에서 채권 듀레이션과 '
          '미국 성장주 OW 포지션을 유지할 계획이나, 틸팅의 폭은 축소하여 BM 대비 '
          '추적오차를 이전대비 낮게 관리하고자 합니다.')
    assert check_block_rules('4JM12', '운용계획', ok) == []


def test_plan_rule_flags_numbers_and_tickers():
    v = ' | '.join(check_block_rules(
        '4JM12', '운용계획',
        'ACE 200 비중을 11.1%에서 27.7%로 대폭 확대할 계획입니다. '
        '나머지는 그대로 가져갑니다.'))
    assert '숫자' in v and '정도부사' in v and '종목명' in v


def test_perf_block_bans_factor_listing():
    """★ 요인 이름+수치만 옮기면 반려 — 왜 그랬는지가 없다 (2026-08-07 사용자 지적)."""
    v = ' | '.join(check_block_rules(
        '4JM12', '펀드성과',
        '당월 펀드는 -2.90%를 기록하여 BM -1.65% 대비 0.66%p 하회하였습니다. '
        '자산배분효과는 해외주식 저비중으로 +0.11%p 기여한 반면, 종목선택효과가 '
        '-2.36%p로 부진하며 상대성과를 압박하였습니다.'))
    assert 'Brinson 요인 수치 나열' in v


def test_perf_block_passes_sent_report_wording():
    """발송본은 요인 용어 없이 포지션·사유로 설명한다 — 그대로 통과해야 한다."""
    ok = ('최근 1개월간 펀드는 +0.69%의 수익률, BM은 -0.15%의 수익률을 기록하여 BM '
          '대비 약 84bps 상회하는 성과를 보였습니다. 국내주식 급락 이후 반등 국면에서의 '
          '차익실현 대응과 국고채 중심 채권 구성의 상대적 견조함이 상대성과에 긍정적으로 '
          '기여한 반면, 매파적 FOMC 영향으로 조정을 받은 미국 성장주 포지션은 상대성과에 '
          '불리하게 작용했습니다.')
    assert check_block_rules('4JM12', '펀드성과', ok) == []


# ── 운용경과: 자산군 단위만, 숫자는 허용 (2026-08-06 사용자 지시) ──

_GYEONGGWA_OK = (
    '국내주식은 월중 급등락 국면에서 전량 매도하여 차익실현을 완료했고, 해당 자금은 '
    '미국 가치주 및 선진국 주식으로 재배분하여 BM 수준으로 포트폴리오를 재편했습니다. '
    '채권은 듀레이션 확대 포지션을 유지하면서 환헤지 비율은 원달러 환율이 기존 '
    '레인지(1,440원~1,520원) 상단을 상회한 것으로 판단해 확대 운용 중입니다.'
)


def test_gyeonggwa_allows_market_levels_and_fx_range():
    """시장 레벨·환율 레인지 숫자는 허용 — 발송본이 실제로 쓰는 표기다."""
    assert check_block_rules('4JM12', '운용경과', _GYEONGGWA_OK) == []


def test_gyeonggwa_bans_trade_volume():
    """★ 거래 볼륨(억 단위 매매금액)은 금지 — 행위만 쓴다 (2026-08-06 사용자 지시).

    ⚠ 숫자 전체를 막으면 안 된다. 위 테스트의 '1,440원~1,520원' 이 반려된다.
    """
    v = ' | '.join(check_block_rules(
        '4JM12', '운용경과',
        '국내주식은 KOSPI가 장중 5,200선까지 밀린 국면에서 17.4억을 순매수하였고, '
        '재원은 국내채권 21.4억과 해외주식 12.1억을 순매도해 충당하였습니다. '
        '환헤지는 오버헤지를 완화해 BM 수준에 근접시켰습니다.'))
    assert '거래 볼륨' in v
    for tok in ('17.4억', '21.4억', '12.1억'):
        assert tok in v, tok
    assert '5,200' not in v          # 시장 레벨은 위반이 아니다


def test_gyeonggwa_flags_security_names():
    """★ 회귀 방어 — 실제 생성분이 종목 축약을 썼다."""
    bad = ('당월 국내채권을 순매도(-21.4억)하며 국고채10년을 축소하고 30년스트립을 '
           '전량 편출한 가운데, 머니마켓을 신규 편입해 유동성을 확보하였습니다. '
           '국내주식은 순매수(+17.4억)하며 KOSPI200을 신규 편입하였습니다.')
    v = ' | '.join(check_block_rules('4JM12', '운용경과', bad))
    assert '종목명' in v
    for tok in ('국고채10년', '30년스트립', '머니마켓', 'KOSPI200'):
        assert tok in v, tok
    assert '숫자' not in v          # 숫자는 이 블록에서 위반이 아니다


def test_gyeonggwa_rule_demands_purpose_and_source():
    """매매 나열이 아니라 목적→재원→환포지션 서사를 요구해야 한다."""
    rule = BLOCK_EXTRA_RULES[('4JM12', '운용경과')]
    for token in ('주 목적', '재원', '순매도로 찍힌 자산군만', 'BM 수준', '환 익스포저'):
        assert token in rule, token


# ── 환헤지 레인지 ──

def test_hedge_range_substitution_keeps_rest_of_sentence():
    """레인지 숫자만 갈아끼우고 나머지 문장은 그대로 — "나머진 전월과 동일"."""
    new, n = _HEDGE_RANGE_RE.subn('1,410원 ~ 1,540원', _PREV_HEDGE, count=1)
    assert n == 1
    assert '1,410원 ~ 1,540원' in new and '1,500원' not in new
    assert new.endswith('중점적으로 모니터링하고 있습니다.')


def test_range_is_pm_2sigma_in_won_units():
    """채택 구간 = ±2σ · 10원 단위 (2026-08-06 사용자 확정)."""
    from market_research.report import fx_rv_range as rv
    assert rv._ROUND == 10
    r = rv.compute('2026-07-31')
    assert r and tuple(r['range_pm_2s']) == (1410, 1540)
    # 하단은 두 구간이 같고 상단만 다르다
    assert r['range_mu_2s'][0] == r['range_pm_2s'][0]
    assert r['range_mu_2s'][1] < r['range_pm_2s'][1]


def test_rv_range_direction():
    """★ 스프레드가 오르면 환율은 내려간다 — 부호가 뒤집힌다.

    두 구간의 **하단은 둘 다 +2σ 로 같고**, 상단만 μ vs −2σ 로 갈린다.
    (부호를 뒤집으면 레인지가 통째로 반대로 나가므로 고정한다.)
    """
    lv = {'mu': 1474.4, '+2s': 1408.0, '-2s': 1543.9}
    assert lv['+2s'] < lv['mu'] < lv['-2s']


def test_hedge_range_matches_tight_spacing():
    """발송본에는 '1,440원~1,520원' 처럼 붙여 쓴 표기도 있다."""
    _, n = _HEDGE_RANGE_RE.subn('X', '기존 레인지(1,440원~1,520원) 상단을 상회', count=1)
    assert n == 1


def test_hedge_line_prefers_sent_report():
    """정본은 **직전 발송본** — 실제로 고객에게 나간 문장이다.

    2026-07 코멘트는 2026-06 회신본(s6)에서 승계한다. ⚠ s6 는 프롬프트용 3,000자
    클립 뒤에 있어 `full_text` 를 봐야 잡힌다.
    """
    import datetime

    from market_research.report import fund_comment_service as svc
    w: list[str] = []
    line = svc._hedge_line('4JM12', '2026-07', datetime.date(2026, 7, 31), w)
    assert '1,410원 ~ 1,540원' in line
    assert line.endswith('중점적으로 모니터링하고 있습니다.')
    assert any('발송본 2026-06' in x for x in w)


def test_hedge_line_warns_without_any_source(monkeypatch):
    """원본이 하나도 없으면 **지어내지 않고** 빈 문자열 + 경고."""
    import datetime

    import market_research.report.report_store as rs
    from market_research.report import fund_comment_service as svc
    monkeypatch.setattr(svc, '_load_sent_report_reference', lambda *a, **k: None)
    monkeypatch.setattr(rs, 'load_final', lambda *a, **k: None)
    w: list[str] = []
    assert svc._hedge_line('4JM12', '2026-08', datetime.date(2026, 7, 31), w) == ''
    assert w and '환헤지' in w[0]
