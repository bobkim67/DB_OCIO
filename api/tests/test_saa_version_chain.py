# -*- coding: utf-8 -*-
"""SAA 리밸 버전 체인 — 카드(Brinson)와 기간별 표(period-returns)의 정합.

★ 회귀 방어 (2026-09-02 사용자 리포트): 08N33 설정후가 카드 5.91% / 표 5.30% 로
  갈렸다. 표 경로(`_load_saa_series`)가 `load_saa_components(as_of)` 의 **최신 셋
  하나**를 전 기간에 적용해, 리밸(2025-12-30) 이전 구간이 아직 존재하지도 않던
  비중으로 계산됐다. Brinson 은 `load_bm_versions` 로 구간별 비중을 쓴다.
  같은 실패 유형이 07G04 에서 "+0.955%p 이탈"로 이미 기록돼 있다.

DB 접속이 필요한 테스트라 실패 시 skip 한다(단위 로직은 _period_bounds 계열과 달리
합성지수 전체를 타야 의미가 있다).
"""
from __future__ import annotations

from datetime import date

import pytest

END = date(2026, 8, 31)
SAA_FUNDS = ["08N33", "08N81", "08P22"]


def _pair(fund: str):
    from api.services.brinson_service import build_brinson
    from api.services.overview_service import build_period_returns
    from config.funds import FUND_META

    inc = str((FUND_META.get(fund) or {}).get("inception") or "")
    if len(inc) != 8:
        pytest.skip(f"{fund} inception 없음")
    start = date(int(inc[:4]), int(inc[4:6]), int(inc[6:8]))
    card = build_brinson(fund, start_date=start, end_date=END,
                         saa_mode="auto").period_bm_return
    tbl = (build_period_returns(fund, end_date=END.isoformat())
           .bm_period_returns or {}).get("SI")
    if card is None or tbl is None:
        pytest.skip(f"{fund} SAA 미산출")
    return float(card), float(tbl) * 100.0


@pytest.mark.parametrize("fund", SAA_FUNDS)
def test_saa_si_matches_between_card_and_table(fund):
    """설정후 SAA 는 카드와 표가 같아야 한다 (리밸 버전 체인 + 설정일 당일 포함)."""
    try:
        card, tbl = _pair(fund)
    except Exception as exc:  # DB 미접속 등
        pytest.skip(f"{fund} 산출 실패: {type(exc).__name__}")
    assert card == pytest.approx(tbl, abs=0.01), (
        f"{fund} 설정후 SAA 불일치 — 카드 {card:.4f}% vs 표 {tbl:.4f}%")


def test_08n33_has_multiple_saa_versions():
    """08N33 이 2버전이어야 이 회귀가 의미를 갖는다 — 버전이 1개로 줄면 알린다."""
    try:
        from modules.data_loader import load_bm_versions
        vers = load_bm_versions("08N33")
    except Exception as exc:
        pytest.skip(f"DB 미접속: {type(exc).__name__}")
    assert len(vers) >= 2, (
        "08N33 SAA 리밸 버전이 2개 미만 — 버전 체인 회귀 테스트가 무력해진다")


def test_versioned_series_differs_from_latest_only():
    """구간별 비중 ≠ 최신 비중 고정 — 둘이 같아지면 체인이 꺼진 것이다."""
    try:
        from api.services.overview_service import _saa_versioned_series
        from modules.data_loader import load_bm_versions, load_saa_components
        vers = load_bm_versions("08N33")
        chained = _saa_versioned_series("08N33", vers, "20250930", END)
    except Exception as exc:
        pytest.skip(f"DB 미접속: {type(exc).__name__}")
    assert chained is not None and len(chained) > 0
    latest = load_saa_components("08N33", "20260831")
    w_latest = {c["name"]: c["weight"] for c in latest["components"]}
    w_first = {c["name"]: c["weight"] for c in vers[0][1]["components"]}
    assert w_first != w_latest, "첫 버전과 최신 버전 비중이 같으면 회귀 검증 불가"
