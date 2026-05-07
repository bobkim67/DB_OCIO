# -*- coding: utf-8 -*-
"""asset_movement_anchor._period_dates 의 period boundary 옵션 A 회귀.

기존 동작:
    "2026-04" → start=2026-04-01, end=2026-04-30   (anchor)
    cf. comment_engine._load_bm_returns_for_range 는 전월말(3/31) → 4/30

수정 후:
    "2026-04" → start=2026-03-31, end=2026-04-30   (전월말 시프트)
    "2026-Q2" → start=2026-03-31, end=2026-06-30
    csv 에 전월말 row 가 있으면 그 값이 첫 in-range row 로 사용되어 dual-source 정합

LLM 호출 0.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ──────────────────────────────────────────────────────────────────
# 1. _period_dates 표준 케이스
# ──────────────────────────────────────────────────────────────────

def test_period_dates_month_uses_prev_calendar_day_as_start():
    from market_research.report.asset_movement_anchor import _period_dates

    s, e = _period_dates("2026-04")
    assert s == date(2026, 3, 31), f"start should be 2026-03-31, got {s}"
    assert e == date(2026, 4, 30), f"end should be 2026-04-30, got {e}"


def test_period_dates_month_january_year_boundary():
    from market_research.report.asset_movement_anchor import _period_dates

    s, e = _period_dates("2026-01")
    assert s == date(2025, 12, 31), f"start should be 2025-12-31, got {s}"
    assert e == date(2026, 1, 31), f"end should be 2026-01-31, got {e}"


def test_period_dates_month_december():
    from market_research.report.asset_movement_anchor import _period_dates

    s, e = _period_dates("2026-12")
    assert s == date(2026, 11, 30), f"start should be 2026-11-30, got {s}"
    assert e == date(2026, 12, 31), f"end should be 2026-12-31, got {e}"


def test_period_dates_quarter_q2():
    from market_research.report.asset_movement_anchor import _period_dates

    s, e = _period_dates("2026-Q2")
    assert s == date(2026, 3, 31), f"start should be 2026-03-31, got {s}"
    assert e == date(2026, 6, 30), f"end should be 2026-06-30, got {e}"


def test_period_dates_quarter_q1_year_boundary():
    from market_research.report.asset_movement_anchor import _period_dates

    s, e = _period_dates("2026-Q1")
    assert s == date(2025, 12, 31), f"start should be 2025-12-31, got {s}"
    assert e == date(2026, 3, 31), f"end should be 2026-03-31, got {e}"


def test_period_dates_quarter_q4():
    from market_research.report.asset_movement_anchor import _period_dates

    s, e = _period_dates("2026-Q4")
    assert s == date(2026, 9, 30), f"start should be 2026-09-30, got {s}"
    assert e == date(2026, 12, 31), f"end should be 2026-12-31, got {e}"


def test_period_dates_invalid():
    from market_research.report.asset_movement_anchor import _period_dates

    s, e = _period_dates("invalid")
    assert s is None and e is None


# ──────────────────────────────────────────────────────────────────
# 2. 정합성 — 3/31 row 가 csv 에 있을 때 anchor 가 그것을 사용
# ──────────────────────────────────────────────────────────────────

def _make_csv_with_prev_month_end(tmp_path: Path,
                                   kap_3_31: float = 271.67,
                                   kap_4_1: float = 274.2954,
                                   kap_4_30: float = 272.5258,
                                   msci_3_31: float = 7909.45,
                                   msci_4_1: float = 175.80,
                                   msci_4_30: float = 10337.20,
                                   sp_3_31: float = 6528.52,
                                   sp_4_1: float = 1043.86,
                                   sp_4_30: float = 7209.01) -> Path:
    """3/31 + 4/1 + 4/30 3개 row csv. 옵션 A 후 첫 in-range row=3/31 가 됨."""
    csv_text = (
        "date,DXY,USDKRW,SP500_TR,MSCI_KOREA,GOLD,US_HY_OAS,FED_UPPER,"
        "UST_7_10Y_TR,KAP_BOND_TR,HY_TR\n"
        f"2026-03-31,103.0,1450.0,{sp_3_31},{msci_3_31},2300.0,320.0,5.50,180.0,"
        f"{kap_3_31},2900.04\n"
        f"2026-04-01,103.5,1455.0,{sp_4_1},{msci_4_1},2310.0,322.0,5.50,180.5,"
        f"{kap_4_1},2911.03\n"
        f"2026-04-30,104.5,1500.0,{sp_4_30},{msci_4_30},2400.0,340.0,5.50,178.5,"
        f"{kap_4_30},2949.11\n"
    )
    fp = tmp_path / "indicators.csv"
    fp.write_text(csv_text, encoding="utf-8")
    return fp


def test_kap_anchor_uses_prev_month_end_when_csv_has_3_31(tmp_path):
    """KAP_BOND_TR 4/30 = 272.5258, 3/31 = 271.67 → +0.3150% (comment_engine 일치)."""
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_csv_with_prev_month_end(tmp_path)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    bond = by_ac["국내채권"]
    # 271.67 → 272.5258 = +0.3150%
    assert bond["bm"]["return_pct"] is not None
    assert abs(bond["bm"]["return_pct"] - 0.3150) < 0.005, \
        f"KAP return should be ~+0.3150%, got {bond['bm']['return_pct']}"
    assert bond["movement_direction"] == "up"
    # level_start 가 3/31 값 사용 (4/1 274.2954 가 아닌)
    assert abs(bond["bm"]["level_start"] - 271.67) < 0.001, \
        f"level_start should be 271.67 (3/31), got {bond['bm']['level_start']}"
    assert abs(bond["bm"]["level_end"] - 272.5258) < 0.001


def test_msci_korea_anchor_uses_prev_month_end(tmp_path):
    """MSCI_KOREA 동일 패턴: 3/31 → 4/30."""
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    # 단순화된 매끈한 가정값으로 검증 (실제 BM과 무관)
    ind = _make_csv_with_prev_month_end(tmp_path,
                                         msci_3_31=100.0, msci_4_1=102.0,
                                         msci_4_30=130.69)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    eq = by_ac["국내주식"]
    # 100 → 130.69 = +30.69%
    assert abs(eq["bm"]["return_pct"] - 30.69) < 0.01
    assert eq["bm"]["level_start"] == 100.0
    assert eq["bm"]["level_end"] == 130.69


def test_sp500_anchor_uses_prev_month_end(tmp_path):
    """SP500_TR 동일 패턴."""
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    ind = _make_csv_with_prev_month_end(tmp_path,
                                         sp_3_31=1000.0, sp_4_1=1010.0,
                                         sp_4_30=1104.23)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    eq = by_ac["해외주식"]
    # 1000 → 1104.23 = +10.423%
    assert abs(eq["bm"]["return_pct"] - 10.423) < 0.01
    assert eq["bm"]["level_start"] == 1000.0
    assert eq["bm"]["level_end"] == 1104.23


# ──────────────────────────────────────────────────────────────────
# 3. csv 에 전월말 row 가 없을 때 기존 fallback (in-range 첫 row) 유지
# ──────────────────────────────────────────────────────────────────

def test_anchor_fallback_when_prev_month_row_missing(tmp_path):
    """3/31 row 없음 → 첫 in-range row=4/1 사용 (기존 로직 그대로 backward)."""
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    fp = tmp_path / "indicators.csv"
    # 3/31 row 부재 — 4/1, 4/30 두 row 만
    fp.write_text(
        "date,DXY,USDKRW,SP500_TR,MSCI_KOREA,GOLD,US_HY_OAS,FED_UPPER,"
        "UST_7_10Y_TR,KAP_BOND_TR,HY_TR\n"
        "2026-04-01,103.5,1455.0,1043.86,175.80,2310.0,322.0,5.50,180.5,"
        "274.2954,2911.03\n"
        "2026-04-30,104.5,1500.0,1144.90,223.91,2400.0,340.0,5.50,178.5,"
        "272.5258,2949.11\n",
        encoding="utf-8",
    )
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=fp,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    bond = by_ac["국내채권"]
    # 274.2954 → 272.5258 = -0.6451% (이전 4/1 시작 값 — fallback)
    assert abs(bond["bm"]["return_pct"] - (-0.6451)) < 0.01, \
        f"fallback should yield -0.6451% from 4/1 → 4/30, got {bond['bm']['return_pct']}"
    assert bond["movement_direction"] == "down"
    assert abs(bond["bm"]["level_start"] - 274.2954) < 0.001


# ──────────────────────────────────────────────────────────────────
# 4. dual-source consistency — comment_engine 패턴과 동일 결과
# ──────────────────────────────────────────────────────────────────

def test_anchor_matches_comment_engine_pattern(tmp_path):
    """csv 에 전월말 row 있을 때 anchor return = (end-prev_end)/prev_end *100,
    이는 comment_engine._load_bm_returns_for_range 의 (cur/prev - 1)*100 과 동일.
    """
    from market_research.report.asset_movement_anchor import (
        build_asset_movement_anchors,
    )
    # 임의 값
    ind = _make_csv_with_prev_month_end(tmp_path,
                                         kap_3_31=200.0, kap_4_1=210.0,
                                         kap_4_30=205.0)
    out = build_asset_movement_anchors(
        period="2026-04", causal_paths=[], evidence_annotations=[],
        indicators_csv_path=ind,
    )
    by_ac = {a["asset_class"]: a for a in out["asset_movements"]}
    anchor_ret = by_ac["국내채권"]["bm"]["return_pct"]
    expected_ret = (205.0 / 200.0 - 1) * 100  # +2.5%
    assert abs(anchor_ret - expected_ret) < 0.001, \
        f"anchor should match comment_engine pattern: expected {expected_ret}, got {anchor_ret}"
