# -*- coding: utf-8 -*-
"""날짜창 ↔ 기간 키 매핑 — PPT 가 코멘트 화면과 같은 스킴을 쓰기 위한 계층.

★ 회귀 방어 (2026-09-02 사용자 리포트): 08N33 설정이후 PPT 와 하반기 PPT 의 시장
  코멘트가 거의 동일했다. PPT 가 `end_date` 로만 period 키를 만들어 두 구간이 같은
  월간 승인본 하나를 읽었기 때문이다. DB·LLM 없이 순수 함수만 검증한다.
"""
from __future__ import annotations

import pytest

from market_research.report.market_payload import months_covering, window_to_period


def test_months_excludes_start_month_when_start_is_month_end():
    """시작이 월말이면 그 달은 뺀다 — 기초일 규약 `(기초일, 기간말]`."""
    got = months_covering("2025-09-30", "2026-08-31")
    assert got[0] == "2025-10", "9/30 하루만 걸치는 2025-09 가 들어가면 안 된다"
    assert got[-1] == "2026-08"
    assert len(got) == 11


def test_months_includes_partial_start_month():
    """시작이 월중이면 그 달도 포함한다."""
    assert months_covering("2026-06-15", "2026-08-31")[0] == "2026-06"


def test_months_single_month():
    assert months_covering("2026-07-31", "2026-08-31") == ["2026-08"]


@pytest.mark.parametrize("start,end,expect", [
    ("2026-07-31", "2026-08-31", ("2026-08", "월별", 2026, 8)),
    ("2025-12-31", "2026-01-31", ("2026-01", "월별", 2026, 1)),
    ("2026-06-30", "2026-09-30", ("2026-Q3", "분기", 2026, 3)),
    ("2025-12-31", "2026-08-31", ("2026-YTD", "YTD", 2026, 0)),
])
def test_window_to_period_maps_calendar_windows(start, end, expect):
    assert window_to_period(start, end) == expect


@pytest.mark.parametrize("start,end", [
    ("2026-05-31", "2026-08-31"),   # 롤링 3M — 분기 경계가 아니다
    ("2026-02-28", "2026-08-31"),   # 롤링 6M — 반기 경계가 아니다
    ("2025-09-30", "2026-08-31"),   # 설정후 — 달력 기간이 아니다
])
def test_window_to_period_returns_none_for_rolling(start, end):
    """롤링·설정후는 키가 없다 → 호출부가 월간 병합으로 폴백해야 한다."""
    assert window_to_period(start, end) is None


def test_quarter_start_is_ambiguous_with_half_and_prefers_narrower():
    """⚠ 6/30 시작은 Q3·H2 시작일이 같아 날짜만으로 구분되지 않는다.

    더 좁은 QTD 를 고른다. 그래서 PPT 는 **기간 유형을 명시적으로 보내야** 하며
    (period 키), 이 매핑은 폴백 전용이다.
    """
    assert window_to_period("2026-06-30", "2026-08-31") == ("2026-Q3.QTD", "QTD", 2026, 3)


def test_invalid_window_is_none():
    assert window_to_period("2026-08-31", "2026-08-31") is None   # 폭 0
    assert window_to_period("2026-09-30", "2026-08-31") is None   # 역전
    assert window_to_period("bad", "2026-08-31") is None
