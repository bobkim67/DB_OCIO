"""Brinson endpoint smoke tests (schema only, 값은 snapshot 에서 락)."""
from __future__ import annotations

import urllib.parse


def _enc(s: str) -> str:
    return urllib.parse.quote(s, safe="")


def test_brinson_08K88_default_returns_200(client):
    r = client.get("/api/funds/08K88/brinson")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "08K88"
    assert body["mapping_method"] in ("방법1", "방법2", "방법3", "방법4")
    assert body["pa_method"] == "8"
    assert body["fx_split"] is True
    for k in ("period_ap_return", "period_bm_return",
              "total_alloc", "total_select", "total_cross",
              "total_excess", "total_excess_relative",
              "fx_contrib", "residual",
              "asset_rows", "sec_contrib", "daily_brinson"):
        assert k in body


def test_brinson_4JM12_default_method_is_방법4(client):
    """FUND_DEFAULT_MAPPING_METHOD['4JM12'] = '방법4' 자동 적용."""
    r = client.get("/api/funds/4JM12/brinson")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "4JM12"
    assert body["mapping_method"] == "방법4"


def test_brinson_explicit_dates(client):
    r = client.get(
        "/api/funds/08K88/brinson",
        params={"start_date": "2026-01-08", "end_date": "2026-03-12"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["start_date"] == "2026-01-08"
    assert body["end_date"] == "2026-03-12"


def test_brinson_pa_method_5(client):
    r = client.get(
        "/api/funds/08K88/brinson",
        params={"start_date": "2026-01-08", "end_date": "2026-03-12",
                "pa_method": "5"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pa_method"] == "5"
    if not body["meta"]["is_fallback"]:
        # 5분류 축소: 8 자산군 → 5 + (있을 경우)기타
        assert len(body["asset_rows"]) <= 6


def test_brinson_fx_off_drops_fx_row(client):
    r_on = client.get(
        "/api/funds/08K88/brinson",
        params={"start_date": "2026-01-08", "end_date": "2026-03-12",
                "fx_split": "true"},
    )
    r_off = client.get(
        "/api/funds/08K88/brinson",
        params={"start_date": "2026-01-08", "end_date": "2026-03-12",
                "fx_split": "false"},
    )
    body_on = r_on.json()
    body_off = r_off.json()
    if body_on["meta"]["is_fallback"]:
        return
    on_classes = {row["asset_class"] for row in body_on["asset_rows"]}
    off_classes = {row["asset_class"] for row in body_off["asset_rows"]}
    if "FX" in on_classes:
        assert "FX" not in off_classes


def test_brinson_mapping_method_4_options(client):
    """방법1~4 모두 200 + total_excess 동일 (Streamlit 회귀 검증과 동일)."""
    base = {"start_date": "2026-01-08", "end_date": "2026-03-12"}
    excess_values = []
    for m in ("방법1", "방법2", "방법3", "방법4"):
        r = client.get("/api/funds/08K88/brinson", params={**base, "mapping_method": m})
        assert r.status_code == 200, f"method {m} failed"
        body = r.json()
        assert body["mapping_method"] == m
        if not body["meta"]["is_fallback"]:
            excess_values.append(body["total_excess"])
    if len(excess_values) == 4:
        # 4개 방법 total_excess 불변 (Streamlit handoff 검증분과 동일)
        for v in excess_values[1:]:
            assert abs(v - excess_values[0]) < 1e-3, \
                f"excess varied across methods: {excess_values}"


def test_brinson_fund_not_found(client):
    r = client.get("/api/funds/XXXXX/brinson")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "FUND_NOT_FOUND"


def test_brinson_invalid_date_format(client):
    r = client.get(
        "/api/funds/08K88/brinson",
        params={"start_date": "2026/01/08"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAM"


def test_brinson_invalid_mapping_method(client):
    r = client.get(
        "/api/funds/08K88/brinson",
        params={"mapping_method": "방법9"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAM"


def test_brinson_invalid_pa_method(client):
    r = client.get(
        "/api/funds/08K88/brinson",
        params={"pa_method": "10"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAM"


def test_brinson_start_after_end(client):
    r = client.get(
        "/api/funds/08K88/brinson",
        params={"start_date": "2026-04-01", "end_date": "2026-01-01"},
    )
    assert r.status_code == 400


def test_brinson_db_failure_fallback(client, monkeypatch):
    """compute 실패 시 200 + is_fallback=true + 빈 배열."""
    import api.services.brinson_service as svc

    def _none(*a, **kw):
        return None

    monkeypatch.setattr(svc, "_compute_cached", _none)
    r = client.get(
        "/api/funds/08K88/brinson",
        params={"start_date": "2026-01-08", "end_date": "2026-03-12"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["asset_rows"] == []
    assert body["sec_contrib"] == []
    assert body["daily_brinson"] == []
