# -*- coding: utf-8 -*-
"""펀드별 월간 보고 기간 창 — 엑셀·코멘트 공용 정의 (2026-08-05 사용자 지시).

## 왜 공용인가

08K88 은 월간 보고 기간이 달력월이 아니다. 엑셀(성과분석)과 코멘트가 각각
기간을 계산하면 **같은 보고서 안에서 수익률이 갈린다** — 실제로 2026-07 에
엑셀 -16.02% vs 코멘트 -11.17% 로 4.85%p 어긋났다. 정의를 여기 한 곳에 둔다.

## 기본 (등록되지 않은 펀드)

달력월. 코멘트는 `(전월 마지막 영업일, 당월 마지막 영업일]` — 전월말 손익을
**제외**한다([[reference_pa_period_start_offbyone]]). 엑셀은 당월 1일~말일.

## 'prev_last_incl_to_last_minus1' (08K88)

**전월 마지막 영업일부터(포함) 당월 마지막 영업일 −1영업일까지.**

2026-07 → 6/30 ~ 7/30. 기준가로는 6/29 종가 → 7/30 종가 = -16.02%
(사용자 확인 기대값). 달력 7월(-11.17%)과 다른 이유는 두 날짜다:
  6/30 (+1.13%) 이 들어오고, **7/31 (+6.98%) 이 빠진다.**

⚠ 기본 규약과 반대로 전월 마지막 영업일 손익을 **포함**한다. 착오가 아니라
  2026-08-05 사용자가 수치(-16.02%)로 확인한 사양이다.
"""

from __future__ import annotations

from datetime import date

# 펀드 → 월간 창 규칙. 미등록 펀드는 달력월(기존 동작).
FUND_MONTH_WINDOW = {
    '08K88': 'prev_last_incl_to_last_minus1',
}


def _to_date(s: str) -> date:
    return date.fromisoformat(s) if '-' in s else date(
        int(s[:4]), int(s[4:6]), int(s[6:8]))


def month_window(fund_code: str, year: int, month: int) -> dict | None:
    """펀드별 월간 창. 규칙 미등록이거나 캘린더 조회 실패면 None (호출부가 기본 동작).

    Returns
    -------
    dict | None
        base       : date — 기준(분모) 종가일. BM 지수 비율·보유 기초 스냅샷용.
        first_incl : date — 손익이 포함되는 첫 영업일. PA·거래 시작일.
        last       : date — 기간 마지막 영업일 (포함).

    `first_incl` 은 `base` 의 **다음 영업일**이다 — 즉 수익률은 base 종가 →
    last 종가로 측정된다.
    """
    rule = FUND_MONTH_WINDOW.get(fund_code)
    if rule != 'prev_last_incl_to_last_minus1':
        return None

    import calendar
    from modules.data_loader import load_business_days_set

    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    last_dom = calendar.monthrange(year, month)[1]
    bdays = sorted(load_business_days_set(
        f'{py}{pm:02d}01', f'{year}{month:02d}{last_dom:02d}'))
    cur = [d for d in bdays if d[:7] == f'{year}-{month:02d}']
    prev = [d for d in bdays if d[:7] == f'{py}-{pm:02d}']
    # 당월 영업일 2개 이상(−1영업일 계산) + 전월 영업일 2개 이상(base 계산) 필요
    if len(cur) < 2 or len(prev) < 2:
        return None

    return {
        'base': _to_date(prev[-2]),        # 전월 마지막 영업일의 직전 영업일
        'first_incl': _to_date(prev[-1]),  # 전월 마지막 영업일 (포함)
        'last': _to_date(cur[-2]),         # 당월 마지막 영업일 − 1영업일
    }
