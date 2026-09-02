# -*- coding: utf-8 -*-
"""자산군 구조 코멘트 + 수치 정책 회귀가드 (2026-09-02 사용자 지시).

## 무엇을 고정하는가

1. **시장코멘트 본문 = 총론 + 자산군별** — 종전 "테마 기준 3~4문단" 으로 돌아가면
   09(자산군별) → 산문 평탄화 → 시드에서 자산군 재구성이라는 축 이중 파괴가 되살아난다.
2. **09 가 하류 3곳에 직접 들어간다** — 본문(synthesis) · 전망(Step 3) · 시드.
   종전엔 본문에만 들어가고 전망·시드는 압축된 본문만 봤다.
3. **수치 정책** — 원칙 배제 + 예외는 레벨 블록의 레벨·고저. 고저는 종가 기준.
4. **09 발췌가 문장/줄 경계에서 끊긴다** — 하드컷이면 마지막 리스크가 반쪽만 간다.
5. **자산군 상한 > 09 파일 수** — 8 이면 sorted() 마지막(환율FX)이 조용히 누락된다.
"""
from __future__ import annotations

import re

import pytest


# ──────────────────────────────────────────
# 1. 본문 구조 — 총론 + 자산군별
# ──────────────────────────────────────────

def _monthly_structure_instruction() -> str:
    """`_synthesize_debate` 월간 분기의 structure_instruction 소스를 읽어온다."""
    import inspect

    from market_research.report import debate_engine as de
    return inspect.getsource(de._synthesize_debate)


def test_monthly_structure_is_total_plus_per_asset():
    src = _monthly_structure_instruction()
    assert '1문단 [총론]' in src
    assert '[자산군별]' in src
    assert '자산군마다 한 문단' in src
    # 근거 없는 자산군은 생략 — 빈칸을 지어내지 않는다
    assert '문단을 통째로 생략' in src
    # 종전 테마 구조로 회귀하지 않았는지
    assert '2문단: 안도와 리스크의 공존' not in src


def test_structure_uses_canonical_market_order():
    """문단 순서는 core.asset_class.MARKET_ORDER 를 그대로 쓴다 (하드코딩 금지)."""
    from market_research.core.asset_class import MARKET_ORDER

    src = _monthly_structure_instruction()
    assert 'MARKET_ORDER' in src
    # 시드 조립 순서와 같은 상수여야 축이 맞는다
    assert MARKET_ORDER[0] == '해외주식' and MARKET_ORDER[-1] == 'FX'


def test_rule2_no_longer_forbids_per_asset_paragraphs():
    """★ '자산별 개별 나열 금지' 가 산개의 직접 원인이었다 — 되살아나면 안 된다."""
    src = _monthly_structure_instruction()
    assert '자산별 개별 나열 금지' not in src


# ──────────────────────────────────────────
# 2. 수치 정책
# ──────────────────────────────────────────

def test_numeric_policy_is_minimise_with_level_exception():
    src = _monthly_structure_instruction()
    assert '수치는 최소화' in src
    assert '특정 시점 수치' in src          # 금지 대상 명시
    assert '종가 기준' in src               # 고저 기준 명시
    assert '장중' in src                    # 장중 표현 금지 경고


def test_ref_rule_does_not_solicit_numbers():
    """ref 규칙이 수치 인용을 유도하면 규칙 3 과 충돌한다 (2026-08 실측 원인)."""
    src = _monthly_structure_instruction()
    assert '수치가 포함된 사실 서술' not in src
    assert 'ref 는 사실의 출처 표시이지 수치 인용의 근거가 아닙니다' in src


def test_good_example_has_no_point_in_time_numbers():
    """예시가 규칙을 어기면 규칙보다 예시가 이긴다."""
    src = _monthly_structure_instruction()
    # 종전 예시의 일간 등락률
    assert 'KOSPI는 +14.4%' not in src
    assert 'KOSPI200은 +16.3%' not in src


# ──────────────────────────────────────────
# 3. 09 주입 — 본문 / 전망 / 시드
# ──────────────────────────────────────────

def test_outlook_step3_receives_research_synthesis_and_levels():
    """★ 전망은 펀드 코멘트 '향후 시장전망' 의 원천이다 — 09 가 여기 빠지면 복구 불가."""
    src = _monthly_structure_instruction()
    body = src[src.index('outlook_prompt = ('):]
    assert 'research_synth_block' in body
    assert 'level_block_text' in body


def test_synthesis_prompt_receives_level_block():
    src = _monthly_structure_instruction()
    body = src[src.index('comment_prompt = ('):src.index('outlook_prompt = (')]
    assert 'level_block_text' in body


def test_seed_prompt_carries_research_synthesis():
    from market_research.report.market_seed import _build_prompt

    kw = dict(market_body='본문', next_label='9월', consensus=[], tail_risks=[],
              have_outlook=True, period_label='2026년 8월')
    synth = '## 09 Research Synthesis — naver_research 재종합 (2026-08)\n### 해외주식\n…'
    with_synth = _build_prompt(synth=synth, **kw)
    assert synth in with_synth
    # 09 가 있으면 '원문' 의 범위가 브리핑 + 09 로 넓어진다
    assert '[09 Research Synthesis] 에 있는 사실만' in with_synth
    # 없어도 생성은 계속된다 (fail-open)
    assert '09 Research Synthesis' not in _build_prompt(synth=None, **kw).split('## 작업')[0]


def test_seed_synthesis_loader_is_fail_open(monkeypatch):
    import market_research.report.market_seed as ms

    monkeypatch.setattr(
        'market_research.report.debate_engine.build_research_synthesis_context',
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    assert ms._research_synthesis_for('2026-08') == ''
    assert ms._research_synthesis_for('헛소리') == ''


def test_seed_synthesis_months_exclude_the_base_date():
    """기초일은 **직전 기간의 마지막 날**이라 그 달은 대상 구간이 아니다.

    2026-08 의 기초일은 7/31 이므로 09 는 2026-08 만 읽어야 한다. 7월을 끌어오면
    지난달 컨센서스가 이번 달 시드에 섞인다.
    """
    import market_research.report.market_seed as ms

    seen = {}

    def fake(y, m, **kw):
        seen['months'] = kw.get('months')
        return 'BLOCK'

    import market_research.report.debate_engine as de
    orig = de.build_research_synthesis_context
    de.build_research_synthesis_context = fake
    try:
        assert ms._research_synthesis_for('2026-08') == 'BLOCK'
        assert seen['months'] == ['2026-08']
        ms._research_synthesis_for('2026-Q2')
        assert seen['months'] == ['2026-04', '2026-05', '2026-06']
    finally:
        de.build_research_synthesis_context = orig


# ──────────────────────────────────────────
# 4. 09 발췌 — 경계 컷
# ──────────────────────────────────────────

def test_cut_at_sentence_keeps_whole_sentences():
    from market_research.report.debate_engine import _cut_at_sentence

    t = '첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다.'
    out = _cut_at_sentence(t, 30)
    assert out.endswith('다.')
    assert len(out) <= 30
    # cap 이 넉넉하면 원문 그대로
    assert _cut_at_sentence(t, 999) == t


def test_cut_at_sentence_falls_back_to_hard_cut():
    """cap 앞쪽에 문장 끝이 없으면(=한 문장이 너무 길면) 하드컷으로 물러난다."""
    from market_research.report.debate_engine import _cut_at_sentence

    t = '가' * 500 + '다.'
    out = _cut_at_sentence(t, 100)
    assert len(out) == 100


def test_synth_claims_cut_on_line_boundary():
    """반쪽 claim 을 남기면 안 된다 — 줄 단위로 끊는다."""
    from market_research.report.debate_engine import _extract_synth_claims

    body = ('## 4. 근거 claim (broker)\n'
            + '\n'.join(f'- [claim:{i:010d}] ' + '가' * 60 for i in range(10)))
    out = _extract_synth_claims(body, 200)
    for ln in out.splitlines():
        if ln.startswith('- '):
            assert ln.endswith('가')          # 잘린 줄이 없다
    assert len(out) <= 200


# ──────────────────────────────────────────
# 5. 자산군 상한
# ──────────────────────────────────────────

def test_asset_cap_exceeds_actual_09_page_count():
    """★ 상한이 파일 수와 같으면 sorted() 마지막(환율FX)이 조용히 누락된다."""
    from market_research.report.debate_context_policy import RESEARCH_ONLY_POLICY
    from market_research.wiki.paths import RESEARCH_SYNTHESIS_DIR

    cap = RESEARCH_ONLY_POLICY.research_synthesis_max_assets
    assert cap >= 12
    if RESEARCH_SYNTHESIS_DIR.exists():
        by_period: dict[str, int] = {}
        for fp in RESEARCH_SYNTHESIS_DIR.glob('*_*.md'):
            by_period[fp.stem.split('_', 1)[0]] = by_period.get(fp.stem.split('_', 1)[0], 0) + 1
        if by_period:
            assert max(by_period.values()) < cap, (
                f'09 페이지 수가 상한에 도달했다: {by_period}')


# ──────────────────────────────────────────
# 6. 레벨 블록 — 단일 소스 · 금리 단위
# ──────────────────────────────────────────

def test_level_series_covers_canonical_assets_except_domestic_bond():
    """자산군당 대표 1개. 국내채권만 의도적으로 비어 있다 (SCIP 에 국고채 yield 없음)."""
    from market_research.core.asset_class import CANONICAL_CLASSES
    from market_research.core.market_levels import LEVEL_SERIES

    tagged = {t[5] for t in LEVEL_SERIES if t[5]}
    assert tagged == set(CANONICAL_CLASSES) - {'국내채권'}


def test_yield_series_change_is_bp_not_percent():
    """⚠ 4.71%→4.75% 는 +4bp 이지 '+0.72%' 가 아니다."""
    import market_research.core.market_levels as ml

    kinds = {t[3]: t[6] for t in ml.LEVEL_SERIES}
    assert kinds['미국채 10년물'] == 'yield'
    src = __import__('inspect').getsource(ml.market_level_facts)
    assert "kind == 'yield'" in src and 'bp' in src


def test_seed_and_debate_share_one_level_source():
    """한쪽만 고치면 같은 달 보고서 안에서 레벨이 갈린다."""
    import inspect

    import market_research.report.debate_engine as de
    import market_research.report.market_seed as ms
    from market_research.core.market_levels import market_level_facts

    assert ms._market_level_facts is market_level_facts
    assert 'from market_research.core.market_levels import level_block' in \
        inspect.getsource(de._synthesize_debate)


@pytest.mark.parametrize('period,expect', [
    ('2026-H1', True), ('2026-H2', True), ('2026-H1.HTD', True), ('2026-Q3', True),
])
def test_period_bounds_supports_closed_half(period, expect):
    """반기 debate 도 레벨 블록을 받아야 한다 — `.HTD` 없는 마감 반기 지원."""
    from market_research.core.market_levels import period_bounds

    assert (period_bounds(period) is not None) is expect


# ──────────────────────────────────────────
# 7. 문단 보존 · 라벨 미노출 (2026-09-02 재생성 실측에서 발견)
# ──────────────────────────────────────────

def test_sanitizer_preserves_paragraph_breaks():
    r"""★ 종전 `\s{2,}`→' ' 가 문단 구분(\n\n)까지 뭉갰다.

    프롬프트는 "문단 사이에 빈 줄을 넣으라"고 지시하는데 사후처리가 지워서
    승인본이 늘 한 덩어리였다(2026-08 실측: 개행 0개). 자산군별 구조에서는
    문단 경계가 곧 자산군 경계라 치명적이다.
    """
    from market_research.report.debate_service import sanitize_customer_comment

    src = '첫 문단.  공백 둘.\n\n둘째 문단.\n\n\n\n셋째 문단.   \n\n넷째.'
    out, _ = sanitize_customer_comment(src)
    assert len([p for p in out.split('\n\n') if p.strip()]) == 4
    assert '\n\n\n' not in out          # 3줄 이상은 2줄로 정규화
    assert '공백 둘' in out and '  ' not in out   # 가로 공백은 계속 접는다


def test_prompt_forbids_bracket_labels_in_body():
    """구조 설명용 라벨이 본문에 그대로 나가면 고객이 읽는 문서가 망가진다.

    2026-08 재생성 실측: `[총론]`·`[해외주식]` 등 8개가 본문에 출력됐다.
    """
    src = _monthly_structure_instruction()
    assert '본문에 쓰지 마세요' in src
    assert '라벨·머리표 없이' in src
    # 예시도 라벨을 쓰지 않아야 한다 — 예시가 규칙을 이긴다
    ex = src[src.index('## 좋은 코멘트 예시'):src.index('위 예시의 특징')]
    assert '[총론]' not in ex and '[해외주식]' not in ex
