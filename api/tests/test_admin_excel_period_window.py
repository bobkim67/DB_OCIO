"""엑셀 기간 창 규칙 (2026-08-05 사용자 확정).

08K88 만 **전월 마지막 영업일부터(포함) 당월 마지막 영업일 −1영업일까지**.
나머지 펀드는 종전 `당월 1일 ~ 당월 말일` 그대로 (골든 불변).

★ build_brinson 의 AP 는 `start_date` **당일 손익부터** 포함한다
  (= 기준가로는 start 직전 영업일 종가 → end 종가).
  실측(08K88 2026-07): (7/1, 7/30) → -16.9648% / (6/30, 7/30) → **-16.0226%**.
  사용자 확인 기대값이 -16.02% 이므로 **6/30 을 그대로 넘기는 쪽**이 정답이다.

DB(DWCI10220 영업일 캘린더)를 읽으므로 내부망 전용.
"""
import pytest

from api.routers.admin_funds import _EXCEL_SPECS, _excel_period_window
from market_research.core.period_window import FUND_MONTH_WINDOW, month_window


@pytest.mark.parametrize('y,m,start,end', [
    # 2026-07: 전월 마지막 영업일 6/30 포함 · 당월 말일 7/31 − 1bd = 7/30
    (2026, 7, '2026-06-30', '2026-07-30'),
    (2026, 8, '2026-07-31', '2026-08-28'),
    (2026, 9, '2026-08-31', '2026-09-29'),
    (2026, 1, '2025-12-31', '2026-01-29'),   # 연초 — 전월이 전년 12월
])
def test_08k88_window(y, m, start, end):
    s, e = _excel_period_window('08K88', y, m)
    assert (s.isoformat(), e.isoformat()) == (start, end)


@pytest.mark.parametrize('fund', ['08N33', '08N81', '08P22'])
def test_other_funds_keep_calendar_month(fund):
    """골든 불변 — 기존 3펀드는 달력월 그대로."""
    s, e = _excel_period_window(fund, 2026, 7)
    assert (s.isoformat(), e.isoformat()) == ('2026-07-01', '2026-07-31')
    assert month_window(fund, 2026, 7) is None


def test_unregistered_fund_falls_back_to_calendar_month():
    s, e = _excel_period_window('07G04', 2026, 8)
    assert (s.isoformat(), e.isoformat()) == ('2026-08-01', '2026-08-31')


def test_08k88_end_is_strictly_before_month_end():
    """기말이 당월 마지막 영업일보다 앞서야 규칙이 적용된 것."""
    from modules.data_loader import load_business_days_set
    _, e = _excel_period_window('08K88', 2026, 7)
    last = max(load_business_days_set('20260701', '20260731'))
    assert e.isoformat() < last


def test_08k88_start_is_prev_month_last_bday():
    """시작일은 **전월** 마지막 영업일 — 당월로 넘어가면 안 된다."""
    from modules.data_loader import load_business_days_set
    s, _ = _excel_period_window('08K88', 2026, 7)
    assert s.isoformat() == max(load_business_days_set('20260601', '20260630'))


def test_base_is_bday_before_first_incl():
    """base 는 first_incl 직전 영업일 — 수익률이 base 종가부터 측정된다.

    ★ 이 관계가 깨지면 코멘트의 BM(분모=base)과 AP(첫 포함일=first_incl)가
      서로 다른 기간이 된다.
    """
    from modules.data_loader import load_business_days_set
    w = month_window('08K88', 2026, 7)
    june = sorted(load_business_days_set('20260601', '20260630'))
    assert w['first_incl'].isoformat() == june[-1]
    assert w['base'].isoformat() == june[-2]


def test_excel_and_comment_share_one_definition():
    """엑셀과 코멘트가 같은 소스를 쓰는지 — 한쪽만 고치면 보고서 안에서 갈린다."""
    s, e = _excel_period_window('08K88', 2026, 7)
    w = month_window('08K88', 2026, 7)
    assert (s, e) == (w['first_incl'], w['last'])


def test_only_08k88_registered():
    assert set(FUND_MONTH_WINDOW) == {'08K88'}


def test_08k88_registered_for_approve_step():
    spec = _EXCEL_SPECS['08K88']
    assert spec['on'] == 'approve' and spec['kind'] == '월간'
    assert spec['brinson'] == {'fx_split': False, 'saa_mode': 'auto'}
