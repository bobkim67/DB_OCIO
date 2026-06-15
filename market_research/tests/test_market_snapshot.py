# -*- coding: utf-8 -*-
"""market_snapshot 순수 함수 테스트 (DB 비의존)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_research.analyze.market_snapshot import (  # noqa: E402
    _parse, _next_month, is_market_metric_text, MARKET_METRICS,
)


def test_parse_dict_currency_key():
    assert _parse('{"USD": 5.62, "KRW": 8476.15}', "KRW") == 8476.15
    assert _parse(b'{"USD": 1507.0, "KRW": 2271049.0}', "USD") == 1507.0


def test_parse_single_number():
    assert _parse("4538.72", None) == 4538.72
    assert _parse("13,284.09", None) == 13284.09


def test_parse_bad():
    assert _parse("not a number", None) is None


def test_next_month_rollover():
    assert _next_month("2026-05") == "2026-06-01"
    assert _next_month("2026-12") == "2027-01-01"


def test_market_metric_text_detection():
    assert is_market_metric_text("코스피 8,000선 돌파")
    assert is_market_metric_text("원/달러 환율 상승")
    assert not is_market_metric_text("반도체 수출 호조")


def test_kospi_config_correct_series():
    # KOSPI 레벨은 ds=15(FG Price) KRW키 — TR(ds=9) 오용 방지 회귀가드
    assert MARKET_METRICS["KOSPI"] == (253, 15, "KRW")
    assert MARKET_METRICS["USDKRW"] == (31, 6, "USD")
