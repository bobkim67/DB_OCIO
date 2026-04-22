def test_holdings_08K88_basic(client):
    r = client.get("/api/funds/08K88/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "08K88"
    assert body["lookthrough_applied"] is False
    assert isinstance(body["asset_class_weights"], list)
    assert isinstance(body["holdings_items"], list)
    if not body["meta"]["is_fallback"]:
        assert len(body["holdings_items"]) >= 1
        # 각 종목 DTO 필수 키
        first = body["holdings_items"][0]
        for k in ("item_cd", "item_nm", "asset_class", "weight", "evl_amt"):
            assert k in first


def test_holdings_08K88_lookthrough(client):
    r = client.get(
        "/api/funds/08K88/holdings",
        params={"lookthrough": "true"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["lookthrough_applied"] is True


def test_holdings_bmless_fund_07G02(client):
    r = client.get("/api/funds/07G02/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "07G02"


def test_holdings_fund_not_found(client):
    r = client.get("/api/funds/XXXXX/holdings")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "FUND_NOT_FOUND"


def test_holdings_invalid_as_of(client):
    r = client.get(
        "/api/funds/08K88/holdings",
        params={"as_of_date": "2026/01/01"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAM"


def test_holdings_db_failure_fallback(client, monkeypatch):
    import api.services.holdings_service as svc

    def _raise(code, as_of, lookthrough):
        raise ConnectionError("db down")

    monkeypatch.setattr(svc, "_load_holdings_df", _raise)
    r = client.get("/api/funds/08K88/holdings")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["holdings_items"] == []
    assert body["asset_class_weights"] == []


def test_holdings_asset_class_sum_reasonable(client):
    r = client.get("/api/funds/08K88/holdings")
    body = r.json()
    if not body["meta"]["is_fallback"]:
        total = sum(w["weight"] for w in body["asset_class_weights"])
        # 유동성 잔차/반올림 고려 허용 오차
        assert total <= 1.10
        assert total >= 0.50


def test_holdings_items_sorted(client):
    r = client.get("/api/funds/08K88/holdings")
    body = r.json()
    if body["holdings_items"]:
        order = [
            "국내주식", "해외주식", "국내채권", "해외채권",
            "대체투자", "FX", "모펀드", "유동성",
        ]
        order_idx = {ac: i for i, ac in enumerate(order)}
        prev_key = (-1, 10.0)
        for it in body["holdings_items"]:
            k = (order_idx.get(it["asset_class"], 99), -it["weight"])
            assert k >= prev_key
            prev_key = k


def test_holdings_empty_fallback(client, monkeypatch):
    """holdings df가 비어있으면 is_fallback=true, 빈 배열"""
    import api.services.holdings_service as svc
    import pandas as pd

    def _empty(code, as_of, lookthrough):
        return pd.DataFrame(columns=["ITEM_CD", "ITEM_NM", "자산군", "EVL_AMT"])

    monkeypatch.setattr(svc, "_load_holdings_df", _empty)
    r = client.get("/api/funds/08K88/holdings")
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["holdings_items"] == []
