def test_macro_basic_defaults(client):
    r = client.get("/api/macro/timeseries")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["series"], list)
    assert body["meta"]["is_fallback"] in (True, False)


def test_macro_explicit_keys_comma(client):
    r = client.get("/api/macro/timeseries", params={"keys": "PE,EPS"})
    assert r.status_code == 200
    body = r.json()
    keys = {s["key"] for s in body["series"]}
    assert keys <= {"PE", "EPS"}


def test_macro_explicit_keys_repeated(client):
    r = client.get(
        "/api/macro/timeseries",
        params=[("keys", "PE"), ("keys", "USDKRW")],
    )
    assert r.status_code == 200
    body = r.json()
    keys = {s["key"] for s in body["series"]}
    assert keys <= {"PE", "USDKRW"}


def test_macro_unknown_key_mixed(client):
    r = client.get(
        "/api/macro/timeseries",
        params={"keys": "PE,ZZZ_UNKNOWN"},
    )
    assert r.status_code == 200
    body = r.json()
    # PE 성공 + ZZZ 실패 → mixed
    if len(body["series"]) > 0:
        assert body["meta"]["source"] == "mixed"
        assert any("unknown" in w for w in body["meta"]["warnings"])


def test_macro_all_unknown_fallback(client):
    r = client.get(
        "/api/macro/timeseries",
        params={"keys": "ZZZ1,ZZZ2"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["series"] == []


def test_macro_invalid_start(client):
    r = client.get(
        "/api/macro/timeseries",
        params={"start": "2026/01/01"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAM"


def test_macro_empty_keys_400(client):
    r = client.get("/api/macro/timeseries", params={"keys": ""})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "INVALID_PARAM"


def test_macro_all_load_failure_fallback(client, monkeypatch):
    import api.services.macro_service as svc

    def _fail(key, start):
        return None

    monkeypatch.setattr(svc, "_load_one_series", _fail)
    r = client.get("/api/macro/timeseries")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["series"] == []


def test_macro_series_structure(client):
    """각 series는 key/label/unit/points 필수, points는 date/value 필수"""
    r = client.get("/api/macro/timeseries", params={"keys": "USDKRW"})
    body = r.json()
    if body["series"]:
        s = body["series"][0]
        for k in ("key", "label", "unit", "points"):
            assert k in s
        if s["points"]:
            p = s["points"][0]
            assert "date" in p
            assert "value" in p
