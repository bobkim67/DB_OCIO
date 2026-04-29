"""Admin debate-status / debate-periods read-only viewer tests.

전부 tmp_path + monkeypatch로 격리. 실파일 의존 없음.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    """report_store.OUTPUT_DIR을 tmp_path로 치환.

    gateway는 lazy import 후 OUTPUT_DIR을 그때그때 읽으므로
    report_store.OUTPUT_DIR만 갈아끼우면 됨.
    """
    from market_research.report import report_store

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)
    return root


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
# debate-status
# ──────────────────────────────────────────────────────────────────


def test_debate_status_full_present(client, tmp_report_root):
    period_dir = tmp_report_root / "2026-04"
    _write_json(period_dir / "_market.input.json", {
        "prepared_at": "2026-04-20T10:00:00",
        "period": "2026-04",
        "fund_code": "_market",
        "evidence_pool": [
            {"title": "t1", "source": "Reuters", "date": "2026-04-01",
             "article_id": "a1"},
            {"title": "t2", "source": "Bloomberg", "date": "2026-04-02",
             "article_id": "a2"},
        ],
        "narrative": {"intro": "..."},
        "benchmarks": {"KOSPI": 1.0, "Gold": 2.0},
        "warnings": [],
        "sources": ["news", "naver_research"],
    })
    _write_json(period_dir / "_market.draft.json", {
        "fund_code": "_market",
        "period": "2026-04",
        "status": "draft_generated",
        "draft_comment": "draft text",
        "consensus_points": ["a", "b"],
        "tail_risks": ["x"],
    })
    _write_json(period_dir / "_market.final.json", {
        "fund_code": "_market",
        "period": "2026-04",
        "status": "approved",
        "approved": True,
        "approved_at": "2026-04-21T12:00:00",
        "approved_by": "admin",
        "final_comment": "final text",
        "consensus_points": ["a", "b"],
        "tail_risks": ["x"],
    })

    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-04", "fund": "_market"})
    assert r.status_code == 200
    body = r.json()

    assert body["period"] == "2026-04"
    assert body["fund_code"] == "_market"
    assert body["status"] == "approved"
    assert body["has_input"] is True
    assert body["has_draft"] is True
    assert body["has_final"] is True

    summary = body["input_summary"]
    assert summary is not None
    assert summary["evidence_count"] == 2
    assert summary["sources_count"] == 2
    assert summary["benchmark_keys"] == ["Gold", "KOSPI"]
    assert len(summary["top_evidence_sample"]) == 2
    assert summary["top_evidence_sample"][0]["title"] == "t1"

    assert body["draft_body"]["draft_comment"] == "draft text"
    assert body["final_body"]["approved"] is True


def test_debate_status_allowed_fund_missing_files(client, tmp_report_root):
    """허용 fund + 비존재 period/fund 조합 → 200 + not_generated."""
    r = client.get("/api/admin/debate-status",
                   params={"period": "2025-01", "fund": "07G04"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_generated"
    assert body["has_input"] is False
    assert body["has_draft"] is False
    assert body["has_final"] is False
    assert body["input_summary"] is None
    assert body["draft_body"] is None
    assert body["final_body"] is None


def test_debate_status_draft_only_status(client, tmp_report_root):
    """draft만 있으면 draft.status를 그대로 반환."""
    period_dir = tmp_report_root / "2026-03"
    _write_json(period_dir / "07G04.draft.json", {
        "fund_code": "07G04",
        "period": "2026-03",
        "status": "edited",
        "draft_comment": "edited text",
    })
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-03", "fund": "07G04"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "edited"
    assert body["has_draft"] is True
    assert body["has_final"] is False
    assert body["draft_body"]["draft_comment"] == "edited text"


def test_debate_status_quarter_period(client, tmp_report_root):
    """period가 YYYY-Q1 형식도 허용."""
    period_dir = tmp_report_root / "2026-Q1"
    _write_json(period_dir / "08K88.draft.json", {
        "fund_code": "08K88",
        "period": "2026-Q1",
        "status": "draft_generated",
    })
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-Q1", "fund": "08K88"})
    assert r.status_code == 200
    assert r.json()["status"] == "draft_generated"


def test_debate_status_fund_not_in_whitelist(client, tmp_report_root):
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-04", "fund": "9999"})
    assert r.status_code == 422


def test_debate_status_fund_path_traversal_dots(client, tmp_report_root):
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-04", "fund": "../../secret"})
    # FastAPI Query max_length 또는 service regex로 차단
    assert r.status_code == 422


def test_debate_status_fund_with_slash(client, tmp_report_root):
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-04", "fund": "07G04/evil"})
    assert r.status_code == 422


def test_debate_status_fund_with_dot_extension(client, tmp_report_root):
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-04", "fund": "07G04.json"})
    assert r.status_code == 422


def test_debate_status_period_regex_violation(client, tmp_report_root):
    # YYYY-M (zero-padding 누락)
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-4", "fund": "07G04"})
    assert r.status_code == 422


def test_debate_status_period_invalid_quarter(client, tmp_report_root):
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-Q5", "fund": "07G04"})
    assert r.status_code == 422


def test_debate_status_period_with_traversal(client, tmp_report_root):
    r = client.get("/api/admin/debate-status",
                   params={"period": "../etc", "fund": "07G04"})
    assert r.status_code == 422


def test_debate_status_market_alias(client, tmp_report_root):
    """_market은 펀드코드가 아니지만 화이트리스트에 포함되어 200."""
    r = client.get("/api/admin/debate-status",
                   params={"period": "2025-12", "fund": "_market"})
    assert r.status_code == 200
    assert r.json()["status"] == "not_generated"


def test_debate_status_corrupt_input_json(client, tmp_report_root):
    """input.json 파싱 실패 시 has_input=False + summary=None로 graceful."""
    period_dir = tmp_report_root / "2026-04"
    period_dir.mkdir(parents=True, exist_ok=True)
    (period_dir / "07G04.input.json").write_text("not-json{",
                                                  encoding="utf-8")
    r = client.get("/api/admin/debate-status",
                   params={"period": "2026-04", "fund": "07G04"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_input"] is False
    assert body["input_summary"] is None
    assert body["status"] == "not_generated"


# ──────────────────────────────────────────────────────────────────
# debate-periods
# ──────────────────────────────────────────────────────────────────


def test_debate_periods_basic(client, tmp_report_root):
    (tmp_report_root / "2026-04").mkdir()
    (tmp_report_root / "2026-03").mkdir()
    (tmp_report_root / "2026-Q1").mkdir()
    # 형식 위반 디렉토리 (걸러져야 함)
    (tmp_report_root / "_evidence_archive").mkdir()
    (tmp_report_root / "2026").mkdir()
    (tmp_report_root / "..").mkdir(exist_ok=True)
    # 파일은 무시
    (tmp_report_root / "_evidence_quality.jsonl").write_text("",
                                                              encoding="utf-8")

    r = client.get("/api/admin/debate-periods")
    assert r.status_code == 200
    body = r.json()
    assert body["periods"] == ["2026-Q1", "2026-04", "2026-03"]


def test_debate_periods_empty(client, tmp_report_root):
    r = client.get("/api/admin/debate-periods")
    assert r.status_code == 200
    assert r.json()["periods"] == []
