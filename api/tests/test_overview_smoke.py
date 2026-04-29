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
    # Week 2: 카드 최대 4개 (since_inception, ytd, mdd, vol)
    assert len(body["cards"]) <= 4
    keys = {c["key"] for c in body["cards"]}
    assert "since_inception" in keys
    assert isinstance(body["nav_series"], list)
    # nav_series 요소의 JSON key는 "date" (alias)
    if body["nav_series"]:
        p = body["nav_series"][0]
        assert "date" in p
        assert "nav" in p


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


# -------------------- Week 2 추가 테스트 --------------------

def test_overview_cards_when_bm_configured(client):
    """08K88은 BM 설정 펀드 → 카드 최대 4개, since_inception 필수"""
    r = client.get("/api/funds/08K88/overview")
    assert r.status_code == 200
    body = r.json()
    keys = {c["key"] for c in body["cards"]}
    assert "since_inception" in keys
    assert len(body["cards"]) >= 1
    assert len(body["cards"]) <= 4
    # 모든 카드의 unit은 Week 2에서 pct
    for c in body["cards"]:
        assert c["unit"] == "pct"


def test_overview_nav_series_has_bm_for_08K88(client):
    """BM OK일 때 nav_series[i].bm 일부 non-null"""
    r = client.get("/api/funds/08K88/overview")
    body = r.json()
    if body["bm_configured"] and not body["meta"]["is_fallback"]:
        if "BM 로딩 실패" not in body["meta"]["warnings"]:
            non_null_bm = [p for p in body["nav_series"] if p.get("bm") is not None]
            assert len(non_null_bm) > 0


def test_overview_bmless_fund_07G02(client):
    """07G02는 bm_configured=false → nav_series.bm/excess 전부 null"""
    r = client.get("/api/funds/07G02/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["bm_configured"] is False
    for p in body["nav_series"]:
        assert p.get("bm") is None
        assert p.get("excess") is None
    # BM 설정 없는 펀드는 source=db (mixed가 아님)
    if not body["meta"]["is_fallback"]:
        assert body["meta"]["source"] == "db"


def test_overview_4jm12_base_preserved(client):
    """4JM12 since_inception 카드 값 = last_nav / 1970.76 - 1 (절대 유지)"""
    r = client.get("/api/funds/4JM12/overview")
    assert r.status_code == 200
    body = r.json()
    card = next(c for c in body["cards"] if c["key"] == "since_inception")
    if body["nav_series"]:
        last_nav = body["nav_series"][-1]["nav"]
        expected = last_nav / 1970.76 - 1.0
        assert abs(card["value"] - expected) < 1e-6


def test_overview_period_returns_keys(client):
    """period_returns 키는 {1M, 3M, 6M, YTD, 1Y, SI} 의 부분집합"""
    r = client.get("/api/funds/08K88/overview")
    body = r.json()
    allowed = {"1M", "3M", "6M", "YTD", "1Y", "SI"}
    assert set(body["period_returns"].keys()) <= allowed


def test_overview_bm_period_returns_keys_when_bm_ok(client):
    """BM 설정 + 로딩 OK일 때 bm_period_returns 키는 {1M, 3M, 6M, YTD, 1Y, SI} 부분집합,
    SI는 항상 포함."""
    r = client.get("/api/funds/08K88/overview")
    body = r.json()
    if not body["bm_configured"] or body["meta"]["is_fallback"]:
        return
    if "BM 로딩 실패" in body["meta"]["warnings"]:
        return
    allowed = {"1M", "3M", "6M", "YTD", "1Y", "SI"}
    bmpr = body["bm_period_returns"]
    assert set(bmpr.keys()) <= allowed
    # bm_aligned 첫 값이 검증되었으므로 SI는 항상 채워져야 함
    assert "SI" in bmpr
    # 값은 raw ratio (절대값 < 10 sanity check — 1000% 미만)
    for v in bmpr.values():
        assert isinstance(v, float)
        assert abs(v) < 10.0


def test_overview_bm_period_returns_empty_for_bmless_fund(client):
    """BM 미설정 펀드(07G02)는 bm_period_returns = {}"""
    r = client.get("/api/funds/07G02/overview")
    body = r.json()
    assert body["bm_configured"] is False
    assert body["bm_period_returns"] == {}


def test_overview_bm_period_returns_empty_when_bm_failed(client, monkeypatch):
    """BM 로더 실패 주입 → bm_period_returns = {}"""
    import api.services.overview_service as svc
    monkeypatch.setattr(svc, "_load_bm_series", lambda code, start: None)
    r = client.get("/api/funds/08K88/overview")
    body = r.json()
    assert body["bm_period_returns"] == {}


def test_overview_bm_period_returns_si_matches_chart(client):
    """SI는 nav_series 마지막 bm / 첫 bm - 1 과 동치 (rebase 전 raw ratio)."""
    r = client.get("/api/funds/08K88/overview")
    body = r.json()
    if not body["bm_configured"] or body["meta"]["is_fallback"]:
        return
    if "BM 로딩 실패" in body["meta"]["warnings"]:
        return
    # nav_series.bm은 first_nav 기준으로 rebase됨 → raw ratio는 (last/first) - 1
    bm_pts = [p["bm"] for p in body["nav_series"] if p.get("bm") is not None]
    if len(bm_pts) < 2:
        return
    # rebase된 시계열에서도 (last/first) - 1은 raw ratio와 같음
    expected_si = bm_pts[-1] / bm_pts[0] - 1.0
    actual_si = body["bm_period_returns"].get("SI")
    assert actual_si is not None
    assert abs(actual_si - expected_si) < 1e-9


def test_overview_bm_failure_mixed_source(client, monkeypatch):
    """BM 로더 실패 주입 → source='mixed', warnings 기록, nav_series.bm 전부 null"""
    import api.services.overview_service as svc
    monkeypatch.setattr(svc, "_load_bm_series", lambda code, start: None)
    r = client.get("/api/funds/08K88/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["source"] == "mixed"
    assert any("BM" in w for w in body["meta"]["warnings"])
    assert all(p.get("bm") is None for p in body["nav_series"])
    assert all(p.get("excess") is None for p in body["nav_series"])


def test_overview_nav_failure_fallback(client, monkeypatch):
    """NAV 로더 실패 주입 → is_fallback=true, cards/nav_series 빈 배열"""
    import modules.data_loader as dl

    def _raise(code, start):
        raise ConnectionError("db down")

    monkeypatch.setattr(dl, "load_fund_nav_with_aum", _raise)
    r = client.get("/api/funds/08K88/overview")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["meta"]["source"] == "mock"
    assert body["cards"] == []
    assert body["nav_series"] == []


def test_overview_nav_empty_fallback(client, monkeypatch):
    """NAV 로더가 빈 DF 반환 → is_fallback=true"""
    import modules.data_loader as dl
    import pandas as pd

    def _empty(code, start):
        return pd.DataFrame(columns=["기준일자", "MOD_STPR", "NAST_AMT", "AUM_억", "DD1_ERN_RT"])

    monkeypatch.setattr(dl, "load_fund_nav_with_aum", _empty)
    r = client.get("/api/funds/08K88/overview")
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["cards"] == []
