# -*- coding: utf-8 -*-
"""P5 03_Assets staging 소비 규칙 테스트 (DB 비의존 부분)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.analyze.research_assets_staging import (  # noqa: E402
    DIRECTIONAL, NON_DIRECTIONAL, NOT_SUPPLIED, ASSET_METRIC, _is_credit,
)


def test_consumption_sets_disjoint_and_complete():
    # 정책 집합이 겹치지 않음
    assert set(DIRECTIONAL) & set(NON_DIRECTIONAL) == set()
    assert set(DIRECTIONAL) & set(NOT_SUPPLIED) == set()
    assert set(NON_DIRECTIONAL) & set(NOT_SUPPLIED) == set()
    # directional = 국내외 주식·채권
    assert set(DIRECTIONAL) == {"국내주식", "해외주식", "국내채권", "해외채권"}
    assert set(NON_DIRECTIONAL) == {"원자재금", "환율(FX)"}
    assert set(NOT_SUPPLIED) == {"기타", "현금성"}


def test_market_metric_only_verified():
    # 검증된 metric 만 등록 (S&P500/NASDAQ100 confirmed; 금리 yield 는 보류)
    assert ASSET_METRIC["국내주식"] == "KOSPI"
    assert ASSET_METRIC["해외주식"] == "SP500"   # ✓검증: 271/ds6 USD (1999=1469.25 실제 종가)
    assert ASSET_METRIC["원자재금"] == "Gold"
    assert ASSET_METRIC["환율(FX)"] == "USDKRW"
    assert "국내채권" not in ASSET_METRIC   # 금리 yield 보류
    assert "해외채권" not in ASSET_METRIC   # 금리 yield 보류


def test_is_credit_detection():
    # _base_primary 가 크레딧이면 credit_sleeve 대상
    credit_claim = {"affected_assets": [{"asset_class": "크레딧", "role": "primary"}],
                    "primary_asset": "크레딧"}
    bond_claim = {"affected_assets": [{"asset_class": "국내채권", "role": "primary"}],
                  "primary_asset": "국내채권"}
    assert _is_credit(credit_claim) is True
    assert _is_credit(bond_claim) is False
