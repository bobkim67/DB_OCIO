import json


def test_evidence_quality_basic(client):
    r = client.get("/api/admin/evidence-quality")
    assert r.status_code == 200
    body = r.json()
    for k in ("rows", "file_path", "total_lines", "returned", "malformed", "meta"):
        assert k in body
    assert isinstance(body["rows"], list)
    assert isinstance(body["meta"]["is_fallback"], bool)


def test_evidence_quality_file_missing(client, monkeypatch, tmp_path):
    import api.services.admin_service as svc
    monkeypatch.setattr(svc, "EVIDENCE_FILE", tmp_path / "nonexistent.jsonl")
    r = client.get("/api/admin/evidence-quality")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["is_fallback"] is True
    assert body["rows"] == []
    assert any("file not found" in w for w in body["meta"]["warnings"])


def test_evidence_quality_malformed_line(client, monkeypatch, tmp_path):
    import api.services.admin_service as svc
    p = tmp_path / "ev.jsonl"
    p.write_text(
        json.dumps({"fund_code": "08K88", "total_refs": 10, "ref_mismatches": 1}) + "\n"
        + "{broken json line\n"
        + json.dumps({"fund_code": "07G04", "total_refs": 4, "ref_mismatches": 0}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "EVIDENCE_FILE", p)
    r = client.get("/api/admin/evidence-quality")
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["source"] == "mixed"
    assert body["malformed"] == 1
    assert body["returned"] == 2
    assert any("parse failed" in w for w in body["meta"]["warnings"])


def test_evidence_quality_limit(client, monkeypatch, tmp_path):
    import api.services.admin_service as svc
    p = tmp_path / "ev.jsonl"
    p.write_text(
        "\n".join(
            json.dumps({"fund_code": f"F{i:02d}", "idx": i}) for i in range(20)
        ) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "EVIDENCE_FILE", p)
    r = client.get("/api/admin/evidence-quality", params={"limit": 5})
    body = r.json()
    assert body["returned"] == 5
    assert body["rows"][-1]["raw"]["idx"] == 19
    assert body["rows"][0]["raw"]["idx"] == 15


def test_evidence_quality_invalid_limit(client):
    r = client.get("/api/admin/evidence-quality", params={"limit": 0})
    # FastAPI Query(ge=1) → 422 자동
    assert r.status_code == 422


def test_evidence_quality_fund_filter(client, monkeypatch, tmp_path):
    import api.services.admin_service as svc
    p = tmp_path / "ev.jsonl"
    p.write_text(
        json.dumps({"fund_code": "08K88", "idx": 1}) + "\n"
        + json.dumps({"fund_code": "07G04", "idx": 2}) + "\n"
        + json.dumps({"fund_code": "08K88", "idx": 3}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(svc, "EVIDENCE_FILE", p)
    r = client.get("/api/admin/evidence-quality", params={"fund_code": "08K88"})
    body = r.json()
    assert body["returned"] == 2
    for row in body["rows"]:
        assert row["fund_code"] == "08K88"
