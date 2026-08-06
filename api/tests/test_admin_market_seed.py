"""Admin 자산군 시드 엔드포인트 (2026-08-05).

GET / PUT(draft) / POST(approve) 만 검증한다 — generate 는 LLM 을 호출하므로
여기서 다루지 않는다(시드 빌더 자체는 market_research/tests 에서 검증).

전부 tmp_path + monkeypatch 격리. 실파일 의존 없음.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    from market_research.report import report_store

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)
    return root


def _write_seed(root: Path, period: str, status: str = "draft") -> None:
    p = root / period / "_market.seed.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "period": period,
        "status": status,
        "sections": {
            "market": {"_총론": "총론.", "국내주식": "국내주식 동향."},
            "outlook": {"국내주식": "국내주식 전망."},
        },
        "source": {"outlook_period": "9월"},
        "generated_at": "2026-09-01T09:00:00",
        "model": "claude-opus-4-8",
        "cost_usd": 0.04,
    }, ensure_ascii=False), encoding="utf-8")


def test_get_seed_not_generated(client, tmp_report_root):
    r = client.get("/api/admin/market-seed", params={"period": "2026-08"})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "not_generated"
    # 시드가 없어도 프론트가 입력 폼을 그릴 수 있도록 순서·자산군은 항상 내려준다
    assert d["market_order"][0] == "해외주식"
    assert d["outlook_order"][0] == "국내주식"
    assert set(d["classes"]) == set(d["market_order"])


def test_get_seed_returns_sections(client, tmp_report_root):
    _write_seed(tmp_report_root, "2026-08")
    d = client.get("/api/admin/market-seed", params={"period": "2026-08"}).json()
    assert d["status"] == "draft"
    assert d["sections"]["market"]["_총론"] == "총론."
    assert d["outlook_period"] == "9월"
    assert d["over_budget"] == []


def test_get_seed_rejects_bad_period(client, tmp_report_root):
    r = client.get("/api/admin/market-seed", params={"period": "not-a-period"})
    assert r.status_code == 422


def test_edit_seed_saves_sections(client, tmp_report_root):
    _write_seed(tmp_report_root, "2026-08")
    r = client.put("/api/admin/market-seed/draft", json={
        "period": "2026-08",
        "sections": {"market": {"_총론": "수정 총론."}, "outlook": {"대체": "금 전망."}},
    })
    assert r.status_code == 200
    d = r.json()
    assert d["sections"]["market"] == {"_총론": "수정 총론."}
    assert d["sections"]["outlook"] == {"대체": "금 전망."}


def test_edit_reverts_approved_to_draft(client, tmp_report_root):
    """★ 승인 후 수정하면 다시 draft — 검수 안 된 문장이 펀드로 새지 않게."""
    _write_seed(tmp_report_root, "2026-08", status="approved")
    d = client.put("/api/admin/market-seed/draft", json={
        "period": "2026-08",
        "sections": {"market": {"_총론": "고침."}, "outlook": {}},
    }).json()
    assert d["status"] == "draft"
    assert d["approved_at"] == ""


def test_edit_missing_seed_404(client, tmp_report_root):
    r = client.put("/api/admin/market-seed/draft", json={
        "period": "2026-08", "sections": {"market": {}, "outlook": {}}})
    assert r.status_code == 404


def test_approve_seed(client, tmp_report_root):
    _write_seed(tmp_report_root, "2026-08")
    d = client.post("/api/admin/market-seed/approve", json={"period": "2026-08"}).json()
    assert d["status"] == "approved"
    assert d["approved_at"]


def test_approve_missing_seed_404(client, tmp_report_root):
    r = client.post("/api/admin/market-seed/approve", json={"period": "2026-08"})
    assert r.status_code == 404


def test_over_budget_surfaced(client, tmp_report_root):
    p = tmp_report_root / "2026-08" / "_market.seed.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "period": "2026-08", "status": "draft",
        "sections": {"market": {"국내주식": "가" * 300}, "outlook": {}},
    }, ensure_ascii=False), encoding="utf-8")
    d = client.get("/api/admin/market-seed", params={"period": "2026-08"}).json()
    assert len(d["over_budget"]) == 1
    assert d["over_budget"][0]["key"] == "국내주식"
    assert d["over_budget"][0]["chars"] == 300
