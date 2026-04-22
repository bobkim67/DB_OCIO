def test_health_returns_status_and_db(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "time" in body
    assert body["version"] == "0.1.0"
    assert "db" in body
    assert body["db"]["status"] in ("ok", "fail")
    assert isinstance(body["db"]["latency_ms"], int)
