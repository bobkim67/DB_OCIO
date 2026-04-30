"""Admin/debug 전용 enrichment 진단 endpoint 테스트.

GET /api/admin/report-enrichment?period=&fund=&limit=
- approved=false 인 final 도 final_unapproved 로 read-only 노출
- internal_source / raw reason / debate_run_id / approved_debate_run_id 모두 노출
- jsonl_rows 는 period+fund 정확 매칭 + debated_at desc + limit
- client endpoint 회귀 누출은 별도 (test_report_smoke.py)
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    """report_store.OUTPUT_DIR 을 tmp_path 로 치환 + indicator_chart macro stub."""
    from market_research.report import report_store
    from api.services import report_service

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)

    def _empty_macro(keys=None, start_date=None):
        from api.schemas.macro import MacroTimeseriesResponseDTO
        from api.schemas.meta import BaseMeta
        from datetime import datetime, timezone
        return MacroTimeseriesResponseDTO(
            meta=BaseMeta(
                as_of_date=None, source="mock",
                sources=[], is_fallback=True,
                warnings=["test stub"],
                generated_at=datetime.now(timezone.utc),
            ),
            series=[],
        )
    monkeypatch.setattr(
        report_service.macro_service, "build_macro_timeseries",
        _empty_macro,
    )

    return root


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


_RUN_ID_A = "a" * 32
_RUN_ID_B = "b" * 32
_RUN_ID_C = "c" * 32


def _approved_final(period: str, fund: str, **extra) -> dict:
    base = {
        "fund_code": fund,
        "period": period,
        "status": "approved",
        "approved": True,
        "approved_at": "2026-04-21T12:00:00",
        "approved_by": "admin",
        "final_comment": f"final {fund} {period}",
        "generated_at": "2026-04-21T11:55:00",
        "model": "claude-opus-4-7",
    }
    base.update(extra)
    return base


def _unapproved_final(period: str, fund: str, **extra) -> dict:
    base = _approved_final(period, fund, **extra)
    base["approved"] = False
    return base


def _draft(period: str, fund: str, **extra) -> dict:
    base = {
        "fund_code": fund,
        "period": period,
        "status": "draft_generated",
        "draft_comment": f"draft {fund} {period}",
        "generated_at": "2026-04-20T10:00:00",
        "validation_summary": {
            "sanitize_warnings": [
                {"type": "ref_mismatch", "message": "sample",
                 "severity": "critical", "ref_no": 3},
            ],
            "warning_counts": {"critical": 1, "warning": 0, "info": 0},
        },
        "evidence_quality": {
            "total_refs": 10, "ref_mismatches": 1,
            "tense_mismatches": 0, "mismatch_rate": 0.1,
            "evidence_count": 15,
        },
        "evidence_annotations": [
            {"ref": 1, "article_id": "a1", "title": "샘플",
             "source": "Reuters", "date": "2026-04-08", "topic": "지정학"},
        ],
        "related_news": [],
    }
    base.update(extra)
    return base


# ────────────────────────────────────────────────────────────────────
# matched_by_id (정상 lineage)
# ────────────────────────────────────────────────────────────────────

def test_admin_enrichment_approved_id_matched_returns_internal(
    client, tmp_report_root,
):
    """approved final + draft ID 일치 → 200 + matched_by_id + internal_source 노출."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_final(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft(period, fund, debate_run_id=_RUN_ID_A),
    )
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["final_status"] == "approved"
    assert body["approved_debate_run_id"] == _RUN_ID_A
    assert body["draft_run_id"] == _RUN_ID_A
    enr = body["enrichment"]
    assert enr is not None
    assert enr["source_consistency_status"] == "matched_by_id"
    # internal_source 노출 (admin 전용)
    assert enr["evidence_annotations_internal_source"] == "draft_json"
    assert enr["validation_summary_internal_source"] == "draft_json"
    # raw reason 노출
    assert "approved_debate_run_id" in (enr["source_consistency_reason"] or "")


def test_admin_enrichment_id_mismatch_exposes_raw_reason(
    client, tmp_report_root,
):
    """approved final + draft ID 불일치 → 200 + id_mismatch + raw reason 노출."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_final(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft(period, fund, debate_run_id=_RUN_ID_B),
    )
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["final_status"] == "approved"
    assert body["approved_debate_run_id"] == _RUN_ID_A
    assert body["draft_run_id"] == _RUN_ID_B
    enr = body["enrichment"]
    assert enr["source_consistency_status"] == "id_mismatch"
    reason = enr["source_consistency_reason"] or ""
    assert _RUN_ID_A in reason
    # client 라우터와 달리 internal_source 그대로
    assert enr["evidence_annotations_internal_source"] == "draft_json"


# ────────────────────────────────────────────────────────────────────
# final_unapproved (admin 전용 노출)
# ────────────────────────────────────────────────────────────────────

def test_admin_enrichment_final_unapproved_exposed(client, tmp_report_root):
    """approved=false 인 final 도 admin 에서는 final_unapproved 로 노출."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _unapproved_final(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft(period, fund, debate_run_id=_RUN_ID_A),
    )
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["final_status"] == "final_unapproved"
    # ID 비교 정보는 그대로 노출
    assert body["approved_debate_run_id"] == _RUN_ID_A
    assert body["draft_run_id"] == _RUN_ID_A
    # enrichment 도 빌드됨 (approved 여부와 무관, lineage 진단 목적)
    assert body["enrichment"] is not None
    assert body["enrichment"]["source_consistency_status"] == "matched_by_id"


def test_client_endpoint_still_blocks_unapproved_final(
    client, tmp_report_root,
):
    """admin 가 노출해도, client `/api/market-report` 는 여전히 404 차단 (회귀)."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _unapproved_final(period, fund),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "REPORT_NOT_APPROVED"


# ────────────────────────────────────────────────────────────────────
# draft_only / not_generated
# ────────────────────────────────────────────────────────────────────

def test_admin_enrichment_draft_only(client, tmp_report_root):
    """final 부재 + draft 존재 → 200 + draft_only + draft_run_id 표시 + final 메타 null."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft(period, fund, debate_run_id=_RUN_ID_C),
    )
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["final_status"] == "draft_only"
    assert body["draft_run_id"] == _RUN_ID_C
    assert body["draft_generated_at"] is not None
    assert body["approved_at"] is None
    assert body["approved_debate_run_id"] is None
    assert body["enrichment"] is None  # final 부재 → enrichment 빌드 안 함


def test_admin_enrichment_not_generated(client, tmp_report_root):
    """final/draft 둘 다 부재 → 200 + not_generated."""
    period, fund = "2026-04", "_market"
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["final_status"] == "not_generated"
    assert body["enrichment"] is None
    assert body["jsonl_rows"] == []


# ────────────────────────────────────────────────────────────────────
# Validation
# ────────────────────────────────────────────────────────────────────

def test_admin_enrichment_invalid_period_returns_422(client, tmp_report_root):
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": "invalid", "fund": "_market"},
    )
    assert r.status_code == 422


def test_admin_enrichment_invalid_fund_returns_422(client, tmp_report_root):
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": "2026-04", "fund": "XXXXX"},
    )
    assert r.status_code == 422


def test_admin_enrichment_path_traversal_blocked(client, tmp_report_root):
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": "2026-04", "fund": "..%2F..%2Fetc"},
    )
    assert r.status_code in (404, 422)


def test_admin_enrichment_market_fund_allowed(client, tmp_report_root):
    """`_market` 화이트리스트 포함."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_final(period, fund),
    )
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    assert r.status_code == 200
    assert r.json()["fund_code"] == "_market"


# ────────────────────────────────────────────────────────────────────
# jsonl_rows: 필터 / 정렬 / limit
# ────────────────────────────────────────────────────────────────────

def test_admin_enrichment_jsonl_filtered_by_period_and_fund(
    client, tmp_report_root,
):
    """jsonl_rows 는 period+fund 정확 매칭 row 만 반환."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_final(period, fund),
    )
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    jsonl.write_text(
        # match
        json.dumps({"period": period, "fund_code": fund,
                    "debate_run_id": _RUN_ID_A,
                    "debated_at": "2026-04-13T14:00:00",
                    "total_refs": 14, "evidence_count": 15}) + "\n"
        # 다른 period
        + json.dumps({"period": "2026-03", "fund_code": fund,
                      "debated_at": "2026-04-13T14:00:00",
                      "total_refs": 99}) + "\n"
        # 다른 fund
        + json.dumps({"period": period, "fund_code": "08K88",
                      "debated_at": "2026-04-13T14:00:00",
                      "total_refs": 88}) + "\n",
        encoding="utf-8",
    )
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    body = r.json()
    assert body["jsonl_total_matched"] == 1
    assert len(body["jsonl_rows"]) == 1
    row = body["jsonl_rows"][0]
    assert row["debate_run_id"] == _RUN_ID_A
    # count alias 의미 분리 노출
    assert row["cited_ref_count"] == 14
    assert row["selected_evidence_count"] == 15
    assert row["uncited_evidence_count"] == 1


def test_admin_enrichment_jsonl_sorted_desc_and_limited(
    client, tmp_report_root,
):
    """debated_at desc 정렬 + limit 적용."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_final(period, fund),
    )
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    rows = []
    for hh in range(10, 20):  # 10개
        rows.append(json.dumps({
            "period": period, "fund_code": fund,
            "debated_at": f"2026-04-13T{hh:02d}:00:00",
            "total_refs": hh,
        }))
    jsonl.write_text("\n".join(rows) + "\n", encoding="utf-8")

    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund, "limit": 3},
    )
    body = r.json()
    assert body["jsonl_total_matched"] == 10
    assert body["jsonl_returned"] == 3
    assert len(body["jsonl_rows"]) == 3
    # desc 정렬
    times = [r["debated_at"] for r in body["jsonl_rows"]]
    assert times == sorted(times, reverse=True)
    assert body["jsonl_rows"][0]["debated_at"].startswith("2026-04-13T19")


def test_admin_enrichment_default_limit_100(client, tmp_report_root):
    """limit 미지정 시 기본 100."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_final(period, fund),
    )
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    rows = []
    for i in range(150):
        # 유효한 datetime 문자열 (분/초만 변경하여 150개 생성)
        mm = (i // 60) + 10
        ss = i % 60
        rows.append(json.dumps({
            "period": period, "fund_code": fund,
            "debated_at": f"2026-04-13T{mm:02d}:{ss:02d}:00",
            "total_refs": i,
        }))
    jsonl.write_text("\n".join(rows) + "\n", encoding="utf-8")
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund},
    )
    body = r.json()
    assert body["jsonl_total_matched"] == 150
    assert body["jsonl_returned"] == 100


def test_admin_enrichment_max_limit_500(client, tmp_report_root):
    """limit 500 초과 요청은 422 (Pydantic Query ge/le)."""
    period, fund = "2026-04", "_market"
    r = client.get(
        "/api/admin/report-enrichment",
        params={"period": period, "fund": fund, "limit": 1000},
    )
    assert r.status_code == 422
