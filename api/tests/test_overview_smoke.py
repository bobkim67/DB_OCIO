def test_funds_list(client):
    r = client.get("/api/funds")
    assert r.status_code == 200
    body = r.json()
    assert "meta" in body and "data" in body
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1
    fund0 = body["data"][0]
    expected_keys = {
        "code", "name", "group", "inception",
        "bm_configured", "default_mapping_method",
    }
    assert expected_keys <= set(fund0.keys())
    # aum 필드 포함 금지 (N+1 방지 원칙)
    assert "aum" not in fund0
    # meta 필드 검증
    assert "generated_at" in body["meta"]
    assert body["meta"]["is_fallback"] in (True, False)


def test_overview_smoke_08K88(client):
    r = client.get("/api/funds/08K88/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "08K88"
    assert "fund_name" in body
    assert "inception_date" in body
    assert isinstance(body["bm_configured"], bool)
    assert "meta" in body
    assert isinstance(body["meta"]["is_fallback"], bool)
    assert body["meta"]["source"] in ("db", "cache", "mock", "mixed")
    assert isinstance(body["cards"], list)
    # Week 1: 카드는 최대 1개 ("since_inception")
    assert len(body["cards"]) <= 1
    if body["cards"]:
        card = body["cards"][0]
        assert card["key"] == "since_inception"
        assert card["unit"] == "pct"
    assert isinstance(body["nav_series"], list)
    # nav_series 요소의 JSON key는 "date" (alias)
    if body["nav_series"]:
        p = body["nav_series"][0]
        assert "date" in p
        assert "nav" in p
        # Week 1: bm / excess는 null
        assert p.get("bm") is None
        assert p.get("excess") is None


def test_overview_fund_not_found(client):
    r = client.get("/api/funds/XXXXX/overview")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["code"] == "FUND_NOT_FOUND"
    assert body["detail"]["message"] == "XXXXX"


def test_overview_invalid_start_date(client):
    r = client.get(
        "/api/funds/08K88/overview",
        params={"start_date": "2026/01/01"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["detail"]["code"] == "INVALID_PARAM"
