"""Report final viewer (client-facing) tests.

전부 tmp_path + monkeypatch로 격리. 실파일 의존 없음.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    """report_store.OUTPUT_DIR 을 tmp_path 로 치환."""
    from market_research.report import report_store

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)
    return root


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _approved_payload(period: str, fund: str, **extra) -> dict:
    base = {
        "fund_code": fund,
        "period": period,
        "status": "approved",
        "approved": True,
        "approved_at": "2026-04-21T12:00:00",
        "approved_by": "admin",
        "final_comment": f"final comment for {fund} {period}",
        "generated_at": "2026-04-21T11:55:00",
        "model": "claude-opus-4-7",
        "consensus_points": ["cp1", "cp2"],
        "tail_risks": ["tr1"],
        "cost_usd": 0.42,
    }
    base.update(extra)
    return base


# ────────────────────────────────────────────────────────────────────
# /api/market-report
# ────────────────────────────────────────────────────────────────────

def test_market_report_approved_returns_200(client, tmp_report_root):
    _write_json(tmp_report_root / "2026-04" / "_market.final.json",
                _approved_payload("2026-04", "_market"))
    r = client.get("/api/market-report", params={"period": "2026-04"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["fund_code"] == "_market"
    assert body["data"]["period"] == "2026-04"
    assert body["data"]["final_comment"].startswith("final comment for _market")
    assert body["data"]["consensus_points"] == ["cp1", "cp2"]
    assert body["data"]["tail_risks"] == ["tr1"]
    assert body["data"]["model"] == "claude-opus-4-7"
    # cost_usd, status는 client 응답 미노출
    assert "cost_usd" not in body["data"]
    assert "status" not in body["data"]
    assert body["meta"]["source"] == "db"


def test_market_report_not_approved_returns_404(client, tmp_report_root):
    """approved=false 인 final.json은 client 노출 금지"""
    payload = _approved_payload("2026-04", "_market", approved=False)
    _write_json(tmp_report_root / "2026-04" / "_market.final.json", payload)
    r = client.get("/api/market-report", params={"period": "2026-04"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_APPROVED"


def test_market_report_missing_returns_404(client, tmp_report_root):
    r = client.get("/api/market-report", params={"period": "2026-04"})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_FOUND"


def test_market_report_invalid_period_returns_422(client, tmp_report_root):
    r = client.get("/api/market-report", params={"period": "invalid"})
    assert r.status_code == 422


def test_market_report_quarterly_period_ok(client, tmp_report_root):
    _write_json(tmp_report_root / "2026-Q1" / "_market.final.json",
                _approved_payload("2026-Q1", "_market"))
    r = client.get("/api/market-report", params={"period": "2026-Q1"})
    assert r.status_code == 200
    assert r.json()["data"]["period"] == "2026-Q1"


# ────────────────────────────────────────────────────────────────────
# /api/funds/{fund}/report
# ────────────────────────────────────────────────────────────────────

def test_fund_report_approved_returns_200(client, tmp_report_root):
    _write_json(tmp_report_root / "2026-Q1" / "08K88.final.json",
                _approved_payload("2026-Q1", "08K88"))
    r = client.get("/api/funds/08K88/report", params={"period": "2026-Q1"})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["fund_code"] == "08K88"
    assert body["data"]["period"] == "2026-Q1"
    assert "final_comment" in body["data"]


def test_fund_report_market_blocked_via_funds_route(client, tmp_report_root):
    """fund 라우터에는 _market 차단 (시장 라우터 분리 원칙)"""
    _write_json(tmp_report_root / "2026-04" / "_market.final.json",
                _approved_payload("2026-04", "_market"))
    r = client.get("/api/funds/_market/report", params={"period": "2026-04"})
    assert r.status_code == 422


def test_fund_report_unknown_fund_returns_422(client, tmp_report_root):
    r = client.get("/api/funds/XXXXX/report", params={"period": "2026-04"})
    assert r.status_code == 422


def test_fund_report_path_traversal_blocked(client, tmp_report_root):
    r = client.get("/api/funds/..%2F..%2Fetc/report",
                   params={"period": "2026-04"})
    assert r.status_code in (404, 422)


def test_fund_report_not_approved_returns_404(client, tmp_report_root):
    payload = _approved_payload("2026-Q1", "08K88", approved=False)
    _write_json(tmp_report_root / "2026-Q1" / "08K88.final.json", payload)
    r = client.get("/api/funds/08K88/report", params={"period": "2026-Q1"})
    assert r.status_code == 404


def test_fund_report_missing_returns_404(client, tmp_report_root):
    r = client.get("/api/funds/08K88/report", params={"period": "2026-Q1"})
    assert r.status_code == 404


# ────────────────────────────────────────────────────────────────────
# approved-periods 엔드포인트
# ────────────────────────────────────────────────────────────────────

def test_market_approved_periods_filters_unapproved(client, tmp_report_root):
    # approved final 2건, unapproved final 1건 → approved 2건만 반환
    _write_json(tmp_report_root / "2026-04" / "_market.final.json",
                _approved_payload("2026-04", "_market"))
    _write_json(tmp_report_root / "2026-Q1" / "_market.final.json",
                _approved_payload("2026-Q1", "_market"))
    _write_json(tmp_report_root / "2026-03" / "_market.final.json",
                _approved_payload("2026-03", "_market", approved=False))
    r = client.get("/api/market-report/approved-periods")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "_market"
    # 정렬: 내림차순 (2026-Q1 vs 2026-04 의 desc 순서는 list_period_dirs 규약 따름)
    assert "2026-04" in body["periods"]
    assert "2026-Q1" in body["periods"]
    assert "2026-03" not in body["periods"]


def test_market_approved_periods_empty_when_none(client, tmp_report_root):
    r = client.get("/api/market-report/approved-periods")
    assert r.status_code == 200
    assert r.json()["periods"] == []


def test_fund_approved_periods_filters_other_funds(client, tmp_report_root):
    """08K88 approved 1건, 4JM12 approved 1건 → 08K88 호출은 1건만"""
    _write_json(tmp_report_root / "2026-Q1" / "08K88.final.json",
                _approved_payload("2026-Q1", "08K88"))
    _write_json(tmp_report_root / "2026-Q1" / "4JM12.final.json",
                _approved_payload("2026-Q1", "4JM12"))
    r = client.get("/api/funds/08K88/report/approved-periods")
    assert r.status_code == 200
    body = r.json()
    assert body["fund_code"] == "08K88"
    assert body["periods"] == ["2026-Q1"]


def test_fund_approved_periods_market_blocked(client, tmp_report_root):
    r = client.get("/api/funds/_market/report/approved-periods")
    assert r.status_code == 422
