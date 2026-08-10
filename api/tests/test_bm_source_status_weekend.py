"""BM 구성지수 신선도 판정 — 주말 as_of 오탐 회귀 방지 (2026-08-10).

배경: 기준가(DWPM10510)는 **주말·공휴일 행도 적재**된다(보수 일할만 반영). 그래서
월요일 아침 as_of 는 일요일이 되는데, 지수는 영업일만 있어 금요일이 최종이다.
종전 판정은 as_of(일요일)를 그대로 목표일로 써서 국내 지수가 통째로 'stale' 로
잡혔다 — 해외(region='ex_KR')만 -1BDay 허용이 있어 우연히 통과했었다.
실측(2026-08-10 월): 11개 펀드 전부 기준가 최신 = 8/9(일), 지수 = 8/7(금),
08N81 에 KOSPI·KAP 10y-20y 2건 오탐.
"""
import pandas as pd
import pytest

from modules import data_loader as dl

# 2026-08 달력: 7(금) 영업일, 8(토)·9(일) 휴일, 10(월) 영업일
_BDAYS = ["20260803", "20260804", "20260805", "20260806", "20260807", "20260810"]


@pytest.fixture
def fake_calendar(monkeypatch):
    """DWCI10220 대체 — DB 없이 결정론적으로 판정."""
    cal = pd.DataFrame({
        "CAL_DT": pd.to_datetime(
            _BDAYS + ["20260808", "20260809"], format="%Y%m%d"),
        "HOLI_FG": ["N"] * len(_BDAYS) + ["Y", "Y"],
    })
    monkeypatch.setattr(dl, "load_holiday_calendar", lambda: cal)


def test_last_kr_business_day_clamps_weekend(fake_calendar):
    f = dl.last_kr_business_day
    assert f("2026-08-07").date().isoformat() == "2026-08-07"   # 금 → 그대로
    assert f("2026-08-08").date().isoformat() == "2026-08-07"   # 토 → 금
    assert f("2026-08-09").date().isoformat() == "2026-08-07"   # 일 → 금
    assert f("2026-08-10").date().isoformat() == "2026-08-10"   # 월 → 그대로


def _comps():
    """08N81 SAA 구성 중 오탐이 났던 국내 2건 + 정상 해외 1건."""
    return [
        {"dataset_id": 253, "dataseries_id": 9, "region": "KR",
         "name": "KOSPI Index"},
        {"dataset_id": 322, "dataseries_id": 9, "region": "KR",
         "name": "KAP Korea Bond Pricing All Index 10y-20y Index"},
        {"dataset_id": 134, "dataseries_id": 6, "region": "ex_KR",
         "name": "MSCI US Large Cap Growth Index"},
    ]


@pytest.fixture
def indices_through_friday(monkeypatch):
    """모든 지수가 금요일(8/7)까지 정상 적재된 상태."""
    fri = pd.Timestamp("2026-08-07")
    monkeypatch.setattr(dl, "_scip_series_max_date", lambda ds, dsr: fri)


def test_weekend_asof_no_false_stale(fake_calendar, indices_through_friday):
    """일요일 as_of(= 주말 기준가 행) 로 조회해도 경고 0건."""
    for d in ("2026-08-08", "2026-08-09"):
        rows = dl.bm_component_source_status(_comps(), pd.Timestamp(d))
        assert rows == [], f"{d}: 주말 오탐 {[r['name'] for r in rows]}"


def test_friday_asof_no_false_stale(fake_calendar, indices_through_friday):
    """영업일 as_of + 같은 날까지 적재 → 경고 0건 (종전 동작 유지)."""
    assert dl.bm_component_source_status(
        _comps(), pd.Timestamp("2026-08-07")) == []


def test_real_lag_still_warns(fake_calendar, monkeypatch):
    """진짜 지연은 그대로 잡는다 — 국내 지수만 수요일에 멈춘 상태, as_of=금요일.

    대체 소스(_BM_FALLBACK)가 있는 KOSPI 도 대체본이 같이 멈췄으므로 'stale'.
    """
    def _max(ds, dsr):
        if ds == 134:                       # 해외는 정상(T-1 허용 안에서 목요일)
            return pd.Timestamp("2026-08-06")
        return pd.Timestamp("2026-08-05")   # 국내 2건 + KOSPI 대체본까지 정지
    monkeypatch.setattr(dl, "_scip_series_max_date", _max)
    rows = dl.bm_component_source_status(_comps(), pd.Timestamp("2026-08-07"))
    assert {r["name"] for r in rows} == {
        "KOSPI Index", "KAP Korea Bond Pricing All Index 10y-20y Index"}
    assert all(r["status"] == "stale" for r in rows)


def test_overview_bm_lag_flag_present(client):
    """응답에 bm_lag 가 실린다 — 프론트는 returns_as_of<as_of 를 직접 비교하지 않는다."""
    body = client.get("/api/funds/08N81/overview").json()
    assert isinstance(body.get("bm_lag"), bool)
    if body["meta"]["is_fallback"]:
        return
    # 주말 as_of 면 lag 로 보지 않는다(기준가 주말 행 = 보수 일할만 반영).
    as_of = body["meta"]["as_of_date"]
    if as_of and pd.Timestamp(as_of).weekday() >= 5:
        assert body["bm_lag"] is False
