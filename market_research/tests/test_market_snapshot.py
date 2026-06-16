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
    _pick_policy_rate, POLICY_RATES,
)

# 합성 indicators.json (FRED/ECOS 캐시 구조 모사 — 파일/DB 비의존)
_MACRO_FIXTURE = {
    "fred": {
        "FED_UPPER": {"data": {"2026-04-30": 4.0, "2026-05-31": 3.75, "2026-06-15": 3.75}},
        "FED_LOWER": {"data": {"2026-04-30": 3.75, "2026-05-31": 3.5, "2026-06-15": 3.5}},
        "ECB_RATE": {"data": {"2026-05-29": 2.0}},
    },
    "ecos": {
        "BOK_RATE": {"data": {"2026-03-01": 2.75, "2026-04-01": 2.5}},  # 월간 (lag)
    },
}


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


def test_us_equity_config_correct_series():
    # S&P500/NASDAQ100 레벨 series 오용 방지 회귀가드 (검증값: docstring/CLAUDE.md)
    # SP500: 271/ds6 USD키 (1999-12-31=1469.25=실제 종가, rebased 아님)
    assert MARKET_METRICS["SP500"] == (271, 6, "USD")
    # NASDAQ100: 272/ds48(PX_LAST)=레벨 — ds=9(TR, 37,269)는 레벨 아님이므로 절대 금지
    assert MARKET_METRICS["NASDAQ100"] == (272, 48, None)
    assert MARKET_METRICS["NASDAQ100"][1] != 9  # TR series 오용 명시 차단


def test_wti_config_correct_series():
    # WTI 유가: dataset 98 단일 ds=15(FG Price) USD키=$/bbl (1999-12-31=25.6=실제 종가)
    assert MARKET_METRICS["WTI"] == (98, 15, "USD")


def test_policy_rate_sources_registered():
    assert set(POLICY_RATES) == {"BOK", "FED", "ECB", "BOJ"}


def test_policy_rate_fed_range_and_month_end():
    # FED = target range(upper/lower), month 말(5/31) 기준 최신값
    r = _pick_policy_rate(_MACRO_FIXTURE, "FED", "2026-05")
    assert r["rate"] == 3.75 and r["range"] == [3.5, 3.75]
    assert r["as_of"] == "2026-05-31" and r["stale_days_to_month_end"] == 0
    assert r["kind"] == "policy_rate"


def test_policy_rate_bok_monthly_lag():
    # BOK 월간 — 2026-05 에 5월 값 없으면 4/1 값 사용 + lag 표시
    r = _pick_policy_rate(_MACRO_FIXTURE, "BOK", "2026-05")
    assert r["rate"] == 2.5 and r["as_of"] == "2026-04-01"
    assert r["stale_days_to_month_end"] == 60  # 4/1 → 5/31
    assert r["range"] is None


def test_policy_rate_respects_month_cutoff():
    # 4월 조회 시 5/31 값을 미래로 보고 가져오지 않음(누수 방지)
    r = _pick_policy_rate(_MACRO_FIXTURE, "FED", "2026-04")
    assert r["rate"] == 4.0 and r["as_of"] == "2026-04-30"


def test_policy_rate_unknown_source_and_empty():
    assert _pick_policy_rate(_MACRO_FIXTURE, "RBA", "2026-05") is None
    assert _pick_policy_rate({}, "FED", "2026-05") is None
