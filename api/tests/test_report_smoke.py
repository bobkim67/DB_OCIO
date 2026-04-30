"""Report final viewer (client-facing) tests.

전부 tmp_path + monkeypatch로 격리. 실파일 의존 없음.
"""
import json
from pathlib import Path

import pytest


@pytest.fixture
def tmp_report_root(tmp_path: Path, monkeypatch) -> Path:
    """report_store.OUTPUT_DIR 을 tmp_path 로 치환.

    indicator_chart 합성도 결정적으로 만들기 위해 기본은 빈 macro_service mock 적용.
    개별 테스트에서 macro 데이터가 필요하면 monkeypatch 로 다시 덮어쓴다.
    """
    from market_research.report import report_store
    from api.services import report_service

    root = tmp_path / "report_output"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(report_store, "OUTPUT_DIR", root)

    # macro_service 호출 결과를 빈 series 로 stub — DB 의존성 제거 + 결정적
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


# ────────────────────────────────────────────────────────────────────
# Enrichment (2026-04-30) — read-time 결합, final.json 불변
# ────────────────────────────────────────────────────────────────────

def _draft_payload(period: str, fund: str, **extra) -> dict:
    """draft.json 샘플. evidence/quality/validation 모두 포함."""
    base = {
        "fund_code": fund,
        "period": period,
        "status": "draft_generated",
        "draft_comment": f"draft for {fund} {period}",
        "consensus_points": ["draft cp"],
        "tail_risks": ["draft tr"],
        "validation_summary": {
            "sanitize_warnings": [
                {"type": "ref_mismatch",
                 "message": "ref 오매핑 sample",
                 "severity": "critical",
                 "ref_no": 3},
                {"type": "fund_action",
                 "message": "펀드 액션 sample",
                 "severity": "warning"},
            ],
            "warning_counts": {"critical": 1, "warning": 1, "info": 0},
        },
        "evidence_quality": {
            "total_refs": 10,
            "ref_mismatches": 1,
            "tense_mismatches": 0,
            "mismatch_rate": 0.1,
            "evidence_count": 15,
        },
        "evidence_annotations": [
            {"ref": 1, "article_id": "abc123",
             "title": "샘플 기사", "url": "https://example.com/1",
             "source": "Reuters", "date": "2026-04-08",
             "topic": "지정학",
             "all_topics": ["지정학", "에너지_원자재"],
             "salience": 0.95,
             "salience_explanation": "TIER1, 교차보도 5건"},
            {"ref": 2, "title": "minimal annotation"},
        ],
        "related_news": [
            {"ref": 11, "article_id": "rel999",
             "title": "관련 뉴스 샘플",
             "source": "뉴시스", "date": "2026-04-08",
             "topic": "크립토"},
        ],
        "coverage_metrics": {
            "available_topics_count": 7,
            "referenced_topics_count": 6,
            "unreferenced_topics": ["부동산"],
            "numeric_sentences_total": 5,
            "uncited_numeric_count": 1,
        },
    }
    base.update(extra)
    return base


def test_enrichment_present_when_draft_lineage_safe(client, tmp_report_root):
    """final.approved_at 보다 draft.generated_at 이 이르면 enrichment 결합 OK.

    Client-facing source = "approved". internal_source 는 client 응답에 없음 (분리됨).
    """
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))  # approved_at=2026-04-21T12:00
    # draft.generated_at = 2026-04-20 (approved_at 이전 → safe)
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-20T10:00:00"),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    # client-facing
    assert enr["evidence_annotations_source"] == "approved"
    assert "evidence_annotations_internal_source" not in enr
    assert len(enr["evidence_annotations"]) == 2
    # related_news
    assert enr["related_news_source"] == "approved"
    assert enr["related_news"][0]["title"] == "관련 뉴스 샘플"
    # evidence_quality (draft + coverage 결합) — count 의미 분리 확인
    assert enr["evidence_quality_source"] == "approved"
    eq = enr["evidence_quality"]
    assert eq["cited_ref_count"] == 10
    assert eq["selected_evidence_count"] == 15
    assert eq["uncited_evidence_count"] == 5  # max(0, 15-10)
    assert eq["ref_mismatch_count"] == 1
    assert eq["mismatch_rate"] == 0.1  # 1/10 ref 기준
    assert eq["coverage_available_topics"] == 7
    # validation_summary
    assert enr["validation_summary_source"] == "approved"
    vs = enr["validation_summary"]
    assert len(vs["sanitize_warnings"]) == 2
    # indicator_chart: macro_service stub 이 빈 series 반환 → unavailable + reason
    # ('approved' 가 아닌 별도 enum 사용)
    assert enr["indicator_chart_source"] == "unavailable"
    assert enr["indicator_chart"]["unavailable_reason"] is not None
    # 전체 정합성
    assert enr["source_consistency_status"] == "older_than_or_equal_final"


def test_enrichment_empty_when_no_draft_no_jsonl(client, tmp_report_root):
    """final.json 만 있고 draft/jsonl 모두 없음 → 모든 enrichment unavailable."""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_annotations"] == []
    assert enr["evidence_annotations_source"] == "unavailable"
    assert "evidence_annotations_internal_source" not in enr
    assert enr["related_news"] == []
    assert enr["related_news_source"] == "unavailable"
    assert enr["evidence_quality"] is None
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["validation_summary"] is None
    assert enr["validation_summary_source"] == "unavailable"


def test_enrichment_quality_jsonl_fallback_when_lineage_safe(client, tmp_report_root):
    """draft.json 부재 시, jsonl 의 lineage-safe row 만 fallback 으로 사용됨.

    여기서는 row 2건 모두 approved_at(2026-04-21) 이전 → safe.
    가장 최신 safe row(2026-04-13T14:53:32) 가 사용됨.
    """
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))  # approved_at=2026-04-21
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    jsonl.write_text(
        json.dumps({"period": period, "fund_code": fund,
                    "debated_at": "2026-04-13T14:09:23",
                    "total_refs": 10, "ref_mismatches": 0,
                    "tense_mismatches": 0, "mismatch_rate": 0.0,
                    "evidence_count": 15, "critical_warnings": 0}) + "\n"
        + json.dumps({"period": period, "fund_code": fund,
                      "debated_at": "2026-04-13T14:53:32",
                      "total_refs": 7, "ref_mismatches": 2,
                      "tense_mismatches": 0, "mismatch_rate": 0.286,
                      "evidence_count": 15, "critical_warnings": 2}) + "\n",
        encoding="utf-8",
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_quality_source"] == "approved"
    assert "evidence_quality_internal_source" not in enr
    eq = enr["evidence_quality"]
    assert eq["cited_ref_count"] == 7
    assert eq["selected_evidence_count"] == 15
    assert eq["uncited_evidence_count"] == 8
    assert eq["mismatch_rate"] == 0.286
    assert eq["critical_warnings"] == 2


def test_enrichment_not_approved_returns_404_no_enrichment(client, tmp_report_root):
    """approved=false 면 enrichment 자체를 노출하지 않음 (404)."""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund, approved=False))
    _write_json(tmp_report_root / period / f"{fund}.draft.json",
                _draft_payload(period, fund))
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 404


def test_enrichment_does_not_mutate_final(client, tmp_report_root):
    """final.json 원본 불변 보장."""
    period, fund = "2026-Q1", "08K88"
    final_path = tmp_report_root / period / f"{fund}.final.json"
    _write_json(final_path, _approved_payload(period, fund))
    original = final_path.read_text(encoding="utf-8")
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-20T10:00:00"),
    )
    r = client.get(f"/api/funds/{fund}/report", params={"period": period})
    assert r.status_code == 200
    after = final_path.read_text(encoding="utf-8")
    assert original == after, "final.json was mutated by API enrichment"


def test_enrichment_fund_report_works(client, tmp_report_root):
    """펀드 라우터에서도 enrichment 정상 작동 (08P22 + lineage safe draft)."""
    period, fund = "2026-04", "08P22"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-20T09:00:00"),
    )
    r = client.get(f"/api/funds/{fund}/report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert len(enr["evidence_annotations"]) == 2
    assert enr["evidence_annotations_source"] == "approved"
    assert "evidence_annotations_internal_source" not in enr


# ────────────────────────────────────────────────────────────────────
# Lineage 정합성 가드 (2026-04-30 강화)
# ────────────────────────────────────────────────────────────────────

def test_lineage_draft_newer_than_approved_blocks_enrichment(client, tmp_report_root):
    """draft.generated_at > final.approved_at 이면
    evidence_annotations / related_news / validation_summary 모두 unavailable."""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))  # approved_at=2026-04-21T12:00
    # draft가 approved 이후 (newer)
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-25T10:00:00"),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    # client-facing 모두 unavailable
    assert enr["evidence_annotations_source"] == "unavailable"
    assert enr["evidence_annotations"] == []
    assert enr["related_news_source"] == "unavailable"
    assert enr["related_news"] == []
    assert enr["validation_summary_source"] == "unavailable"
    assert enr["validation_summary"] is None
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["evidence_quality"] is None
    # client 응답에는 internal source 노출 안 됨
    assert "evidence_annotations_internal_source" not in enr
    # 전체 정합성
    assert enr["source_consistency_status"] == "newer_than_final"
    # client 응답에는 raw reason 대신 살균된 note 만 노출
    assert "source_consistency_reason" not in enr
    note = enr.get("source_consistency_note") or ""
    assert "승인 시점 이후" in note


def test_lineage_jsonl_newer_than_approved_blocks_quality(client, tmp_report_root):
    """jsonl 최신 row 가 approved_at 보다 늦으면 evidence_quality unavailable.
    (draft.json은 부재 → quality는 jsonl fallback 후보였으나 lineage로 차단)"""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))  # approved_at=2026-04-21
    # jsonl: 모두 approved_at 이후
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    jsonl.write_text(
        json.dumps({"period": period, "fund_code": fund,
                    "debated_at": "2026-04-25T14:53:32",
                    "total_refs": 7, "ref_mismatches": 2,
                    "mismatch_rate": 0.286, "evidence_count": 15,
                    "critical_warnings": 2}) + "\n",
        encoding="utf-8",
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_quality"] is None
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["source_consistency_status"] == "newer_than_final"


def test_lineage_draft_older_than_or_equal_allowed(client, tmp_report_root):
    """draft timestamp == approved_at 인 경우도 허용 (matched)."""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))  # approved_at=2026-04-21T12:00:00
    # draft.generated_at == approved_at (정확 일치)
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-21T12:00:00"),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_annotations_source"] == "approved"
    assert enr["source_consistency_status"] == "matched"


# ────────────────────────────────────────────────────────────────────
# Internal-source / raw-reason 누출 방지 (2026-04-30, client/internal DTO 분리)
# ────────────────────────────────────────────────────────────────────

_LEAK_KEYS = (
    "evidence_annotations_internal_source",
    "related_news_internal_source",
    "evidence_quality_internal_source",
    "validation_summary_internal_source",
    "indicator_chart_internal_source",
    "source_consistency_reason",
)

# 살균 검사 — client note 에 들어가면 안 되는 내부 어휘
_FORBIDDEN_TERMS = (
    "draft.json", "final.json", "input.json",
    "draft_json", "final_json", "evidence_quality_jsonl",
    ".jsonl", "draft/jsonl",
)


def _assert_no_leak(enr: dict) -> None:
    leaks = [k for k in _LEAK_KEYS if k in enr]
    assert not leaks, f"client response leaked internal keys: {leaks}"


def _assert_note_sanitized(enr: dict) -> None:
    note = (enr.get("source_consistency_note") or "")
    for term in _FORBIDDEN_TERMS:
        assert term not in note, (
            f"source_consistency_note leaked internal term: {term!r} "
            f"(note={note!r})"
        )


def test_client_response_no_internal_source_when_lineage_safe(
    client, tmp_report_root,
):
    """draft lineage safe 케이스 — client 응답에 internal_source / raw reason 없음."""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-20T10:00:00"),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    _assert_no_leak(enr)
    _assert_note_sanitized(enr)


def test_client_response_no_internal_source_when_lineage_unsafe(
    client, tmp_report_root,
):
    """draft lineage unsafe 케이스에서도 internal_source 노출 금지 + note 살균."""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-25T10:00:00"),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    _assert_no_leak(enr)
    _assert_note_sanitized(enr)
    # status는 그대로 노출
    assert enr["source_consistency_status"] == "newer_than_final"
    # note는 살균된 한 줄
    assert "승인 시점 이후" in (enr.get("source_consistency_note") or "")


def test_client_response_fund_route_also_clean(client, tmp_report_root):
    """펀드 라우터에도 누출 없음."""
    period, fund = "2026-04", "08P22"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-20T09:00:00"),
    )
    r = client.get(f"/api/funds/{fund}/report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    _assert_no_leak(enr)
    _assert_note_sanitized(enr)


# ────────────────────────────────────────────────────────────────────
# P1-① debate_run_id strict matching (2026-04-30)
# ────────────────────────────────────────────────────────────────────

_RUN_ID_A = "a" * 32
_RUN_ID_B = "b" * 32


def test_lineage_matched_by_id_allows_enrichment(client, tmp_report_root):
    """final.approved_debate_run_id == draft.debate_run_id → matched_by_id + 노출.

    timestamp 가 newer 여도 ID 일치하면 허용 (ID strict matching이 timestamp 우선).
    """
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    # ID 일치 + timestamp는 newer (ID 우선이므로 통과해야 함)
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(
            period, fund,
            debate_run_id=_RUN_ID_A,
            generated_at="2026-04-25T10:00:00",  # newer than approved 2026-04-21
        ),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_annotations_source"] == "approved"
    assert len(enr["evidence_annotations"]) == 2
    assert enr["source_consistency_status"] == "matched_by_id"
    note = enr.get("source_consistency_note") or ""
    assert "승인본과 연결된 근거 데이터" in note


def test_lineage_id_mismatch_blocks_enrichment(client, tmp_report_root):
    """final.approved_debate_run_id != draft.debate_run_id → id_mismatch + 차단.

    timestamp 가 safe 여도 ID 불일치면 차단 (timestamp fallback 금지).
    """
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(
            period, fund,
            debate_run_id=_RUN_ID_B,
            generated_at="2026-04-20T10:00:00",  # timestamp는 safe
        ),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_annotations_source"] == "unavailable"
    assert enr["evidence_annotations"] == []
    assert enr["validation_summary_source"] == "unavailable"
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["source_consistency_status"] == "id_mismatch"
    note = enr.get("source_consistency_note") or ""
    assert "승인본과 연결된 근거 데이터가 아니" in note


def test_lineage_id_present_on_final_but_missing_on_draft_blocks(
    client, tmp_report_root,
):
    """final 에 ID 있는데 draft 에 ID 없으면 timestamp safe 여도 차단."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    # draft.debate_run_id 없음 + timestamp는 safe
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-20T10:00:00"),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_annotations_source"] == "unavailable"
    assert enr["source_consistency_status"] == "id_mismatch"


def test_lineage_legacy_final_falls_back_to_timestamp(client, tmp_report_root):
    """final 에 approved_debate_run_id 가 없으면 legacy → timestamp fallback 적용."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund),  # approved_debate_run_id 부재
    )
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, generated_at="2026-04-20T10:00:00"),  # safe
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_annotations_source"] == "approved"
    assert enr["source_consistency_status"] == "older_than_or_equal_final"


def test_lineage_jsonl_id_matched_used_for_quality(client, tmp_report_root):
    """jsonl row.debate_run_id == approved_debate_run_id 면 quality 허용.

    draft.json 부재 → quality 는 jsonl fallback. ID 일치 row 만 사용.
    """
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    jsonl.write_text(
        json.dumps({"period": period, "fund_code": fund,
                    "debate_run_id": _RUN_ID_B,  # 다른 run
                    "debated_at": "2026-04-13T14:09:23",
                    "total_refs": 99}) + "\n"
        + json.dumps({"period": period, "fund_code": fund,
                      "debate_run_id": _RUN_ID_A,  # 일치
                      "debated_at": "2026-04-13T14:53:32",
                      "total_refs": 7, "ref_mismatches": 2,
                      "mismatch_rate": 0.286, "evidence_count": 15,
                      "critical_warnings": 2}) + "\n",
        encoding="utf-8",
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_quality_source"] == "approved"
    eq = enr["evidence_quality"]
    assert eq["cited_ref_count"] == 7  # ID 일치 row 의 값
    assert eq["selected_evidence_count"] == 15
    assert enr["source_consistency_status"] == "matched_by_id"


def test_lineage_jsonl_id_mismatched_blocks_quality(client, tmp_report_root):
    """final 에 ID 있는데 jsonl 모든 row 의 debate_run_id 가 다르면 quality 차단."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    jsonl.write_text(
        json.dumps({"period": period, "fund_code": fund,
                    "debate_run_id": _RUN_ID_B,
                    "debated_at": "2026-04-13T14:53:32",
                    "total_refs": 7}) + "\n",
        encoding="utf-8",
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_quality"] is None
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["source_consistency_status"] == "id_mismatch"


def test_lineage_jsonl_id_missing_when_final_has_id_blocks_quality(
    client, tmp_report_root,
):
    """final 에 ID 있는데 jsonl row 에 debate_run_id 없으면 timestamp safe 여도 차단."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    jsonl = tmp_report_root / "_evidence_quality.jsonl"
    # row 에 debate_run_id 부재 + timestamp 는 safe
    jsonl.write_text(
        json.dumps({"period": period, "fund_code": fund,
                    "debated_at": "2026-04-13T14:53:32",
                    "total_refs": 7, "evidence_count": 15}) + "\n",
        encoding="utf-8",
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_quality"] is None
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["source_consistency_status"] == "id_mismatch"


def test_lineage_client_response_no_id_leak(client, tmp_report_root):
    """client 응답에 debate_run_id / approved_debate_run_id / internal_source /
    raw reason 모두 노출되지 않음."""
    period, fund = "2026-04", "_market"
    _write_json(
        tmp_report_root / period / f"{fund}.final.json",
        _approved_payload(period, fund, approved_debate_run_id=_RUN_ID_A),
    )
    _write_json(
        tmp_report_root / period / f"{fund}.draft.json",
        _draft_payload(period, fund, debate_run_id=_RUN_ID_A,
                       generated_at="2026-04-20T10:00:00"),
    )
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    body = r.json()
    payload_str = json.dumps(body, ensure_ascii=False)
    # data.* 최상위에도 누출 없음
    assert "debate_run_id" not in body["data"]
    assert "approved_debate_run_id" not in body["data"]
    enr = body["data"]["enrichment"]
    _assert_no_leak(enr)
    _assert_note_sanitized(enr)
    # 응답 전체 어디에도 internal source 키 / raw run id 본문 노출 없음
    assert "internal_source" not in payload_str
    assert "approved_debate_run_id" not in payload_str
    assert "debate_run_id" not in payload_str


def test_internal_helper_still_exposes_internal_source(tmp_report_root):
    """Internal _build_enrichment 직접 호출 시 internal_source/raw reason 보존.

    Admin endpoint를 만들 때 이 internal 모델을 base로 사용 가능해야 함.
    """
    from api.services.report_service import _build_enrichment

    period, fund = "2026-04", "_market"
    final_path = tmp_report_root / period / f"{fund}.final.json"
    draft_path = tmp_report_root / period / f"{fund}.draft.json"
    _write_json(final_path, _approved_payload(period, fund))
    _write_json(
        draft_path,
        _draft_payload(period, fund, generated_at="2026-04-25T10:00:00"),
    )
    final = json.loads(final_path.read_text(encoding="utf-8"))
    internal = _build_enrichment(final, period, fund)

    # 내부 모델은 internal_source 필드를 가짐
    assert internal.evidence_annotations_internal_source == "draft_json"
    assert internal.related_news_internal_source == "draft_json"
    assert internal.evidence_quality_internal_source == "draft_json"
    assert internal.validation_summary_internal_source == "draft_json"
    # raw reason 도 유지 (admin/debug용)
    assert internal.source_consistency_status == "newer_than_final"
    assert internal.source_consistency_reason is not None
    assert "approved_at" in (internal.source_consistency_reason or "")


def test_lineage_draft_no_timestamp_is_unverifiable_and_unavailable(
    client, tmp_report_root,
):
    """draft 에 generated_at/debated_at/updated_at/created_at 모두 없으면
    unverifiable → client unavailable."""
    period, fund = "2026-04", "_market"
    _write_json(tmp_report_root / period / f"{fund}.final.json",
                _approved_payload(period, fund))
    # draft에서 모든 timestamp 제거
    draft = _draft_payload(period, fund)
    for k in ("generated_at", "debated_at", "updated_at", "created_at"):
        draft.pop(k, None)
    _write_json(tmp_report_root / period / f"{fund}.draft.json", draft)
    r = client.get("/api/market-report", params={"period": period})
    assert r.status_code == 200
    enr = r.json()["data"]["enrichment"]
    assert enr["evidence_annotations_source"] == "unavailable"
    assert enr["related_news_source"] == "unavailable"
    assert enr["validation_summary_source"] == "unavailable"
    assert enr["evidence_quality_source"] == "unavailable"
    assert enr["source_consistency_status"] == "unverifiable"
    # client 응답에는 internal_source / raw reason 노출 안 됨
    assert "evidence_annotations_internal_source" not in enr
    assert "source_consistency_reason" not in enr
